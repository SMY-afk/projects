"""One-shop official live catch-up after an interrupted daily collection window."""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
from pathlib import Path

from arq.connections import RedisSettings, create_pool

from erp_api.core.config import get_settings
from erp_api.infrastructure.database import Database
from erp_api.services.affiliate_capture_health import AffiliateCaptureHealthRepository
from erp_api.services.affiliate_local_export_service import TARGET_SHOPS
from erp_api.services.affiliate_sample_priority import sample_round_releases_affiliate
from erp_api.workers.affiliate_live_observation import (
    latest_persisted_live_date,
    latest_recent_live_observation,
)
from erp_api.workers.affiliate_live_schedule import _active_live_shops
from scripts.run_auto_live_evidence import (
    execute_one,
    load_analytics_config,
    missing_windows,
    successful_live_runs,
)
from scripts.sample_watch_freshness import SHOPS


async def run(args: argparse.Namespace) -> None:
    load_analytics_config(args.config)
    settings = get_settings()
    if settings.affiliate_export_tenant_id is None:
        raise RuntimeError("Affiliate export tenant is unavailable")
    database = Database(settings.database_url)
    redis = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    try:
        targets = {item.source_name: item.business_name for item in TARGET_SHOPS}
        shops = [
            shop for shop in await _active_live_shops(database)
            if shop.tenant_id == settings.affiliate_export_tenant_id
            and shop.source_name in targets
        ]
        if len(shops) != 5 or {shop.source_name for shop in shops} != set(targets):
            raise RuntimeError("Exact five authorized shops are unavailable")
        selected = [shop for shop in shops if shop.shop_id == SHOPS[args.shop_label]]
        if len(selected) != 1:
            raise RuntimeError("Requested shop identity is unavailable")
        shop = selected[0]
        health = await AffiliateCaptureHealthRepository(redis).get(
            shop.tenant_id, shop.shop_id
        )
        if health.state != "online" or not health.session_available:
            raise RuntimeError("Shop browser health is not ready")
        now = datetime.now(UTC)
        if not await sample_round_releases_affiliate(
            database, shop.tenant_id, shop.shop_id, now=now
        ):
            raise RuntimeError("Shop sample round has not released analytics")
        recent = await latest_recent_live_observation(
            database, shop.tenant_id, shop.shop_id, now=now
        )
        if recent is None:
            persisted = await latest_persisted_live_date(
                database, shop.tenant_id, shop.shop_id
            )
            if persisted is None:
                raise RuntimeError("No persisted live day exists for a bounded probe")
            plan = shop, "probe", persisted, persisted
        else:
            due = missing_windows(
                targets[shop.source_name], recent[0],
                await successful_live_runs(
                    database, shop, targets[shop.source_name]
                ),
            )
            if not due:
                print(f"LIVE_RECOVERY_COMPLETE shop={args.shop_label}")
                return
            plan = shop, "window", *due[0]
        print(
            f"LIVE_RECOVERY_PLAN shop={args.shop_label} kind={plan[1]} "
            f"start={plan[2]} end={plan[3]}", flush=True
        )
        if not args.apply:
            return
        from erp_api.main import build_analytics_services

        service = build_analytics_services(
            settings, database, redis_client=redis
        )["analytics_sync_service"]
        if service is None:
            raise RuntimeError("Official analytics service is unavailable")
        result = await execute_one(database, redis, service, plan, now)
        if result == "shop_locked":
            raise RuntimeError("Shop live sync is already running")
        confirmed = await latest_recent_live_observation(
            database, shop.tenant_id, shop.shop_id, now=datetime.now(UTC)
        )
        if confirmed is None:
            raise RuntimeError("Live observation readback is not fresh")
        if plan[1] == "window":
            remaining = missing_windows(
                targets[shop.source_name], confirmed[0],
                await successful_live_runs(
                    database, shop, targets[shop.source_name]
                ),
            )
            if (plan[2], plan[3]) in remaining:
                raise RuntimeError("Live window coverage was not persisted")
        print(f"LIVE_RECOVERY_STORED {result}", flush=True)
    finally:
        await redis.aclose()
        await database.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--shop-label", choices=tuple(SHOPS), required=True)
    parser.add_argument("--apply", action="store_true")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
