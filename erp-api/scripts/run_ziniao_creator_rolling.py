from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

# Python 3.13 queries WMI while importing SQLAlchemy. A degraded WMI provider
# must not block this isolated Ziniao worker before it reaches the browser.
if os.name == "nt":
    platform._wmi = None  # type: ignore[attr-defined]

from redis.asyncio import Redis
from redis.exceptions import LockError
from sqlalchemy import select

from erp_api.core.config import get_settings
from erp_api.infrastructure.database import Database
from erp_api.models.affiliate_creator import AffiliateCreatorReport
from erp_api.models.shop import Shop
from erp_api.services.affiliate_capture_health import (
    AffiliateCaptureHealthRepository,
)
from erp_api.services.affiliate_official_availability import (
    AffiliateOfficialAvailabilityRepository,
)
from erp_api.services.ziniao_creator_export import detect_latest_creator_date
from erp_api.services.ziniao_webdriver_client import (
    ZiniaoBrowserSession,
    ZiniaoCredentials,
    ZiniaoWebDriverClient,
)
from scripts.ingest_creator_xlsx import _run as ingest_creator_xlsx
from scripts.ingest_creator_xlsx import _running_browser

SHOP_NAME = "Akeleo Toys"
LOCK_KEY = "affiliate:ziniao-creator-rolling:Akeleo-Toys"


def rolling_windows(latest: date) -> list[tuple[date, date, str]]:
    return [
        (latest, latest, "today"),
        (latest - timedelta(days=6), latest, "last7d"),
        (
            latest - timedelta(days=59),
            latest - timedelta(days=30),
            "days31to60",
        ),
        (latest - timedelta(days=29), latest, "last30d"),
    ]


async def run_once() -> dict[str, object]:
    settings = get_settings()
    database = Database(settings.database_url)
    redis = Redis.from_url(settings.redis_url)
    lock = redis.lock(LOCK_KEY, timeout=540)
    acquired = await lock.acquire(blocking=False)
    if not acquired:
        await redis.aclose()
        await database.dispose()
        return {"status": "already_running"}
    try:
        shop = await _shop(database)
        browser = await _ensure_browser(settings)
        if settings.ziniao_chromedriver_path is None:
            raise RuntimeError("Ziniao ChromeDriver path is not configured.")
        up_to = datetime.now(UTC).astimezone(ZoneInfo(shop.timezone)).date()
        latest = await asyncio.to_thread(
            detect_latest_creator_date,
            browser,
            settings.ziniao_chromedriver_path,
            up_to=up_to,
        )
        await AffiliateOfficialAvailabilityRepository(redis).set(
            shop.tenant_id, shop.id, latest
        )
        await AffiliateCaptureHealthRepository(redis).record(
            shop.tenant_id,
            shop.id,
            "online",
            latest_available_date=latest,
            latest_available_dates={"creators": latest},
        )
        await AffiliateCaptureHealthRepository(redis).record_observation(
            shop.tenant_id, shop.id, "creators", latest
        )
        results = []
        for start, end, preset in rolling_windows(latest):
            if await _has_complete_report(database, shop, start, end):
                results.append({"preset": preset, "status": "current"})
                continue
            args = SimpleNamespace(
                shop_name=SHOP_NAME,
                file=None,
                ziniao_latest=False,
                ziniao_export=True,
                window_start=start,
                window_end=end,
                source_row_count=None,
            )
            result = await ingest_creator_xlsx(args)
            results.append(
                {
                    "preset": preset,
                    "status": result["status"],
                    "recordCount": result["recordCount"],
                    "sourceRowCount": result["sourceRowCount"],
                }
            )
        return {
            "status": "succeeded",
            "shop": SHOP_NAME,
            "latestAvailableDate": latest.isoformat(),
            "windows": results,
        }
    finally:
        try:
            await lock.release()
        except LockError:
            pass
        await redis.aclose()
        await database.dispose()


async def _shop(database: Database) -> Shop:
    async with database.system_session_factory() as session:
        rows = (
            await session.scalars(
                select(Shop).where(
                    Shop.shop_name == SHOP_NAME,
                    Shop.platform == "tiktok",
                    Shop.status == "active",
                )
            )
        ).all()
    if len(rows) != 1:
        raise RuntimeError("Akeleo Toys must resolve to one active TikTok shop.")
    return rows[0]


async def _ensure_browser(settings) -> ZiniaoBrowserSession:
    try:
        payload = await _running_browser(settings)
    except RuntimeError:
        return await _start_browser(settings)
    session = _session_from_payload(payload)
    configured = (settings.ziniao_akeleo_browser_name or "").strip()
    if not configured or session.download_path is None:
        raise RuntimeError("Akeleo Toys Ziniao browser is not configured.")
    if session.download_path.name != configured:
        raise RuntimeError("The running Ziniao browser is not Akeleo Toys.")
    return session


async def _start_browser(settings) -> ZiniaoBrowserSession:
    values = (
        settings.ziniao_company,
        settings.ziniao_username,
        settings.ziniao_password,
        settings.ziniao_akeleo_browser_name,
    )
    if not all(values):
        raise RuntimeError("Ziniao credentials and browser name are required.")
    credentials = ZiniaoCredentials(
        settings.ziniao_company,
        settings.ziniao_username,
        settings.ziniao_password.get_secret_value(),
    )
    async with ZiniaoWebDriverClient(settings.ziniao_webdriver_url) as client:
        browsers = await client.list_browsers(credentials)
        matches = [
            browser
            for browser in browsers
            if browser.name == settings.ziniao_akeleo_browser_name
        ]
        if len(matches) != 1:
            raise RuntimeError("Configured Akeleo Toys Ziniao browser was not found.")
        return await client.start_browser(credentials, browser_oauth=matches[0].oauth)


def _session_from_payload(payload: dict[str, object]) -> ZiniaoBrowserSession:
    download_path = Path(str(payload.get("downloadPath") or ""))
    browser_path = Path(str(payload.get("browserPath") or ""))
    return ZiniaoBrowserSession(
        debugging_port=int(payload["debuggingPort"]),
        core_version=str(payload.get("core_version") or ""),
        core_type="Chromium",
        download_path=download_path,
        browser_path=browser_path,
    )


async def _has_complete_report(
    database: Database,
    shop: Shop,
    start: date,
    end: date,
) -> bool:
    async with database.system_session_factory() as session:
        metadata_rows = (
            await session.scalars(
                select(AffiliateCreatorReport.source_metadata).where(
                    AffiliateCreatorReport.tenant_id == shop.tenant_id,
                    AffiliateCreatorReport.shop_id == shop.id,
                    AffiliateCreatorReport.period_start == start,
                    AffiliateCreatorReport.period_end == end,
                    AffiliateCreatorReport.currency == (shop.currency or "USD").upper(),
                    AffiliateCreatorReport.status == "complete",
                )
            )
        ).all()
    return any(
        isinstance(metadata, dict)
        and metadata.get("provider") == "tiktok_compass_creator_xlsx_seller_center"
        for metadata in metadata_rows
    )


async def _watch(interval_seconds: int) -> None:
    settings = get_settings()
    database = Database(settings.database_url)
    redis = Redis.from_url(settings.redis_url)
    shop = await _shop(database)
    stopped = asyncio.Event()
    _heartbeat = asyncio.create_task(
        _run_health_heartbeat(settings, shop, redis, stopped)
    )
    while True:
        try:
            result = await run_once()
        except Exception as error:  # noqa: BLE001 -- daemon retries safely
            result = {"status": "failed", "errorType": type(error).__name__}
        print(json.dumps(result, separators=(",", ":")), flush=True)
        await asyncio.sleep(interval_seconds)


async def _run_health_heartbeat(
    settings, shop: Shop, redis: Redis, stopped: asyncio.Event
) -> None:
    repository = AffiliateCaptureHealthRepository(redis)
    while not stopped.is_set():
        try:
            await _ensure_browser(settings)
            await repository.record(shop.tenant_id, shop.id, "online")
        except Exception:  # noqa: BLE001 -- preserve a truthful offline state
            await repository.record(shop.tenant_id, shop.id, "browser_offline")
        try:
            await asyncio.wait_for(stopped.wait(), timeout=10)
        except TimeoutError:
            pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync rolling Akeleo Creator XLSX.")
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=600)
    args = parser.parse_args()
    if args.interval_seconds < 60:
        raise SystemExit("Interval must be at least 60 seconds.")
    asyncio.run(_watch(args.interval_seconds) if args.watch else run_and_print())


async def run_and_print() -> None:
    print(json.dumps(await run_once(), separators=(",", ":")))


if __name__ == "__main__":
    main()
