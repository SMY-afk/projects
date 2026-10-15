"""Capture TK creator/video dates and independent official live observations."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from arq.connections import RedisSettings, create_pool
from playwright.async_api import async_playwright

from backend.app.services.hubstudio_attached_browser import (
    connect_attached_hubstudio_browser,
)
from backend.app.services.tiktok_affiliate_analytics_page_control import (
    is_affiliate_host,
)
from backend.app.services.tiktok_affiliate_available_date import (
    detect_latest_selectable_dates,
)
from erp_api.core.config import get_settings
from erp_api.infrastructure.database import Database
from erp_api.services.affiliate_capture_health import AffiliateCaptureHealthRepository
from erp_api.services.affiliate_local_export_service import TARGET_SHOPS
from erp_api.workers.affiliate_live_observation import latest_recent_live_observation
from erp_api.workers.affiliate_live_schedule import _active_live_shops
from scripts.daily_valid_creator_core import SHOP_LINES


def parse_shop(value: str) -> tuple[str, str, str]:
    parts = value.split(",", 2)
    if len(parts) != 3 or parts[0] not in SHOP_LINES or not all(parts):
        raise ValueError("--shop must be NAME,PLATFORM_SHOP_ID,CDP_URL")
    return parts[0], parts[1], parts[2]


async def probe_shop(name: str, platform_shop_id: str, cdp_url: str) -> dict:
    async with async_playwright() as playwright:
        browser = await connect_attached_hubstudio_browser(playwright, cdp_url)
        contexts = []
        for context in browser.contexts:
            shop_ids = {
                shop_id
                for page in context.pages
                if is_affiliate_host(urlsplit(page.url).hostname)
                for shop_id in parse_qs(urlsplit(page.url).query).get("shop_id", [])
            }
            if platform_shop_id in shop_ids:
                if shop_ids != {platform_shop_id}:
                    raise RuntimeError(f"{name}: mixed shop identities in CDP")
                contexts.append(context)
        if len(contexts) != 1:
            raise RuntimeError(f"{name}: expected shop missing or ambiguous in CDP")
        dates = await detect_required_dates(contexts)
        if set(dates) != {"creators", "videos"}:
            raise RuntimeError(f"{name}: TK creator/video date could not be verified")
        return {
            "shop": name,
            "observed_at": datetime.now(UTC).isoformat(),
            "creators": dates["creators"].isoformat(),
            "videos": dates["videos"].isoformat(),
        }


async def detect_required_dates(contexts: list) -> dict[str, date]:
    dates = {}
    for resource in ("creators", "videos"):
        for attempt in range(2):
            result = await detect_latest_selectable_dates(contexts, (resource,))
            if resource in result:
                dates[resource] = result[resource]
                break
            if attempt == 0:
                await asyncio.sleep(0.5)
    return dates


async def live_observations() -> dict[str, tuple[str, datetime]]:
    settings = get_settings()
    database = Database(settings.database_url)
    redis = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    try:
        repository = AffiliateCaptureHealthRepository(redis)
        names = {shop.source_name: shop.business_name for shop in TARGET_SHOPS}
        rows = {}
        for shop in await _active_live_shops(database):
            name = names.get(shop.source_name)
            if name is None or shop.tenant_id != settings.affiliate_export_tenant_id:
                continue
            observed = await repository.observed_evidence_for(
                shop.tenant_id, shop.shop_id, "liveAccounts"
            )
            if observed is None:
                observed = await latest_recent_live_observation(
                    database,
                    shop.tenant_id,
                    shop.shop_id,
                    now=datetime.now(UTC),
                )
            if observed is None:
                raise RuntimeError(f"{name}: fresh official live date is unavailable")
            rows[name] = observed[0].isoformat(), observed[1]
        if set(rows) != set(SHOP_LINES):
            raise RuntimeError("Independent live dates are missing for required shops")
        return rows
    finally:
        await redis.aclose()
        await database.dispose()


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shop", action="append", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    shops = [parse_shop(value) for value in args.shop]
    if len(shops) != len(SHOP_LINES) or {name for name, _, _ in shops} != set(
        SHOP_LINES
    ):
        parser.error("Exactly the five required shops must be provided once each")
    rows = [await probe_shop(*shop) for shop in shops]
    lives = await live_observations()
    for row in rows:
        live_day, observed_at = lives[row["shop"]]
        row["liveAccounts"] = live_day
        row["observed_at"] = min(
            datetime.fromisoformat(row["observed_at"]), observed_at
        ).isoformat()
    evidence = {"source": "direct_tk_sources", "shops": rows}
    Path(args.output).write_text(
        json.dumps(evidence, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    print(json.dumps(evidence, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
