from __future__ import annotations

import argparse
import asyncio
import json
import time
from collections import defaultdict
from dataclasses import replace
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

from sqlalchemy import select

from backend.app.services.capture_logging import capture_log
from backend.app.services.tiktok_sample_creator_details_collector import (
    SAMPLE_REQUEST_PATH,
    SampleCreatorDetailsTarget,
)
from backend.app.services.tiktok_sample_creator_details_selenium import (
    TikTokSampleCreatorDetailsSeleniumCollector,
)
from backend.app.services.ziniao_sample_list_selenium import (
    activate_responsive_sample_page,
    capture_ziniao_sample_list,
)
from erp_api.core.config import get_settings
from erp_api.infrastructure.database import Database
from erp_api.main import build_sample_application_services
from erp_api.models.sample_application import SampleApplication
from erp_api.models.shop import Shop
from erp_api.services.sample_application_time_enrichment import (
    SampleApplicationTimeEnrichmentService,
)
from erp_api.services.sample_creator_profile_freshness import (
    creator_profile_refresh_due,
)
from erp_api.services.sample_notification_profile_enrichment import (
    SampleNotificationProfileEnrichmentService,
)
from erp_api.services.ziniao_selenium import attach_selenium, detach_selenium
from scripts.run_ziniao_affiliate_watch import SHOP_NAME
from scripts.run_ziniao_creator_rolling import _ensure_browser
from scripts.run_ziniao_sample_watch import _resolve_cdp_port

MAX_TARGETS = 20
APPLICATION_LIST_INTERVAL_SECONDS = 300
SAMPLE_REQUEST_ORIGIN = "https://affiliate-us.tiktok.com"


async def run_once(*, capture_application_times: bool = True) -> dict[str, object]:
    settings = get_settings()
    database = Database(settings.database_url)
    try:
        shop = await _shop(database)
        targets = await _targets(database, shop.tenant_id, shop.id)
        if not targets and not capture_application_times:
            return {"status": "idle", "targetCount": 0}
        application_ids = frozenset(
            application_id for target in targets for application_id in target.outbox_ids
        )
        await SampleNotificationProfileEnrichmentService(
            database, limit=MAX_TARGETS
        ).enrich(
            tenant_id=shop.tenant_id,
            shop_id=shop.id,
            application_ids=application_ids,
        )
        targets = await _targets(database, shop.tenant_id, shop.id)
        if not targets and not capture_application_times:
            return {"status": "current", "targetCount": 0}
        application_ids = frozenset(
            application_id for target in targets for application_id in target.outbox_ids
        )
        browser_session = await _ensure_browser(settings)
        browser_session = await _resolved_browser_session(
            browser_session, shop.platform_shop_id
        )
        if settings.ziniao_chromedriver_path is None:
            raise RuntimeError("Ziniao ChromeDriver is not configured.")
        activate_responsive_sample_page(
            browser_session.debugging_port,
            shop.platform_shop_id,
        )
        driver = attach_selenium(
            browser_session,
            settings.ziniao_chromedriver_path,
            performance_logs=True,
        )
        captured = 0
        time_result = None
        try:
            _ensure_sample_request_page(driver, shop.platform_shop_id)
            if capture_application_times:
                capture = capture_ziniao_sample_list(
                    driver,
                    shop.platform_shop_id,
                )
                time_result = await SampleApplicationTimeEnrichmentService(
                    database
                ).enrich(
                    tenant_id=shop.tenant_id,
                    shop_id=shop.id,
                    applications=capture.page.applications,
                    observed_at=datetime.now(UTC),
                    request_id=capture.observed_request_id,
                )
                if time_result.application_ids:
                    pipeline = build_sample_application_services(settings, database)[
                        "sample_shop_pipeline_service"
                    ]
                    if pipeline is None:
                        raise RuntimeError("Sample shop pipeline is not configured.")
                    await pipeline.complete_after_source(
                        tenant_id=shop.tenant_id,
                        shop_id=shop.id,
                        source_type="official_api",
                        source_results=(time_result,),
                    )
            if targets:
                captured = await TikTokSampleCreatorDetailsSeleniumCollector(
                    shop.tenant_id,
                    shop.id,
                    shop.platform_shop_id,
                    database,
                ).capture(driver, targets)
        finally:
            detach_selenium(driver)
        result = None
        if application_ids:
            result = await SampleNotificationProfileEnrichmentService(
                database, limit=MAX_TARGETS
            ).enrich(
                tenant_id=shop.tenant_id,
                shop_id=shop.id,
                application_ids=application_ids,
            )
        remaining = await _targets(database, shop.tenant_id, shop.id)
        return {
            "status": "succeeded" if not remaining else "partial",
            "targetCount": len(targets),
            "capturedCount": captured,
            "enrichedCount": result.enriched_count if result else 0,
            "remainingCount": len(remaining),
            "applicationTimeMatched": time_result.matched_count if time_result else 0,
            "applicationTimeUpdated": time_result.updated_count if time_result else 0,
            "applicationTimeMissing": (
                time_result.missing_time_count if time_result else 0
            ),
        }
    finally:
        await database.dispose()


async def _resolved_browser_session(browser_session, platform_shop_id: str):
    debugging_port = await _resolve_cdp_port(
        browser_session.debugging_port, platform_shop_id
    )
    return replace(browser_session, debugging_port=debugging_port)


async def watch(interval_seconds: float) -> None:
    next_application_list_at = 0.0
    while True:
        capture_application_times = time.monotonic() >= next_application_list_at
        try:
            result = await run_once(capture_application_times=capture_application_times)
            if result["status"] != "idle":
                capture_log("sample_creator_details_watch_completed", **result)
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 -- resident watcher boundary
            capture_log(
                "sample_creator_details_watch_failed",
                error_type=type(error).__name__,
            )
        if capture_application_times:
            next_application_list_at = (
                time.monotonic() + APPLICATION_LIST_INTERVAL_SECONDS
            )
        await asyncio.sleep(interval_seconds)


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


async def _targets(
    database,
    tenant_id: UUID,
    shop_id: UUID,
    *,
    now: datetime | None = None,
):
    statement = (
        select(
            SampleApplication.id,
            SampleApplication.creator_username,
            SampleApplication.creator_profile_snapshot,
            SampleApplication.creator_profile_observed_at,
        )
        .where(
            SampleApplication.tenant_id == tenant_id,
            SampleApplication.shop_id == shop_id,
            SampleApplication.platform_status == "PENDING",
        )
        .order_by(SampleApplication.source_observed_at, SampleApplication.id)
    )
    async with database.system_session_factory() as session:
        rows = (await session.execute(statement)).all()
    return _refresh_targets(rows, now=now or datetime.now(UTC))[:MAX_TARGETS]


def _refresh_targets(rows, *, now: datetime):
    grouped: dict[str, set[UUID]] = defaultdict(set)
    for outbox_id, username, snapshot, observed_at in rows:
        if not creator_profile_refresh_due(snapshot, observed_at, now=now):
            continue
        if isinstance(username, str) and username.strip():
            grouped[username.strip().lstrip("@").casefold()].add(outbox_id)
    return [
        SampleCreatorDetailsTarget(username, frozenset(outbox_ids))
        for username, outbox_ids in grouped.items()
    ]


def _ensure_sample_request_page(driver, platform_shop_id: str) -> str:
    matches = []
    original = driver.current_window_handle
    for handle in driver.window_handles:
        driver.switch_to.window(handle)
        split = urlsplit(driver.current_url)
        if split.path == SAMPLE_REQUEST_PATH and parse_qs(split.query).get(
            "shop_id"
        ) == [platform_shop_id]:
            matches.append(handle)
    if matches:
        selected = original if original in matches else matches[0]
        driver.switch_to.window(selected)
        return selected

    driver.switch_to.window(original)
    driver.switch_to.new_window("tab")
    created = driver.current_window_handle
    target_url = (
        f"{SAMPLE_REQUEST_ORIGIN}{SAMPLE_REQUEST_PATH}?shop_id={platform_shop_id}"
    )
    driver.get(target_url)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        split = urlsplit(driver.current_url)
        if split.path == SAMPLE_REQUEST_PATH and parse_qs(split.query).get(
            "shop_id"
        ) == [platform_shop_id]:
            return created
        time.sleep(0.25)
    if created in driver.window_handles:
        driver.close()
    if original in driver.window_handles:
        driver.switch_to.window(original)
    raise RuntimeError("Akeleo Toys sample requests page could not be opened.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Capture pending sample Creator details from Akeleo Toys."
    )
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--interval", type=float, default=10)
    args = parser.parse_args()
    if args.interval <= 0:
        parser.error("--interval must be positive")
    if args.watch:
        asyncio.run(watch(args.interval))
    else:
        print(json.dumps(asyncio.run(run_once()), ensure_ascii=False))


if __name__ == "__main__":
    main()
