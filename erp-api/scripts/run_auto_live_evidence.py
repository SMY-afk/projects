"""Refresh five-shop official live dates and missing rolling windows on ECS."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from arq.connections import RedisSettings, create_pool
from sqlalchemy import select

from erp_api.core.config import get_settings
from erp_api.infrastructure.database import Database
from erp_api.models.analytics_sync import AnalyticsSyncRun
from erp_api.services.affiliate_capture_health import AffiliateCaptureHealthRepository
from erp_api.services.affiliate_local_export_service import TARGET_SHOPS
from erp_api.services.affiliate_sample_priority import sample_round_releases_affiliate
from erp_api.services.affiliate_schedule_queries import (
    daily_collection_window_open,
    latest_due_schedule_date,
)
from erp_api.workers.affiliate_live_observation import (
    latest_persisted_live_date,
    latest_recent_live_observation,
)
from erp_api.workers.affiliate_live_schedule import _active_live_shops, live_windows
from erp_api.workers.analytics_jobs import sync_analytics_job
from scripts.daily_valid_creator_batch import _covered_by_successful_runs

CONFIG_NAMES = (
    "tiktok_video_analytics_url", "tiktok_video_analytics_overview_url",
    "tiktok_video_analytics_items_path", "tiktok_video_analytics_next_page_token_path",
    "tiktok_video_analytics_field_map", "tiktok_video_analytics_external_id_field",
    "tiktok_video_analytics_amount_currency_pairs", "tiktok_video_analytics_required_fields",
    "tiktok_video_analytics_max_window_days", "tiktok_live_analytics_url",
    "tiktok_live_analytics_overview_url", "tiktok_live_analytics_items_path",
    "tiktok_live_analytics_next_page_token_path", "tiktok_live_analytics_field_map",
    "tiktok_live_analytics_external_id_field", "tiktok_live_analytics_amount_currency_pairs",
    "tiktok_live_analytics_required_fields", "tiktok_live_analytics_max_window_days",
)
BUSINESS_NAMES = {target.source_name: target.business_name for target in TARGET_SHOPS}
UNLOCK_IF_OWNED = (
    "if redis.call('get', KEYS[1]) == ARGV[1] "
    "then return redis.call('del', KEYS[1]) else return 0 end"
)


def load_analytics_config(path: Path) -> None:
    values = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(values, dict) or set(values) != set(CONFIG_NAMES):
        raise RuntimeError("Official analytics config shape is invalid")
    if any(value is None or value == "" or value == {} for value in values.values()):
        raise RuntimeError("Official analytics config has an empty field")
    for name, value in values.items():
        os.environ[name.upper()] = value if isinstance(value, str) else json.dumps(value)
    get_settings.cache_clear()


def missing_windows(
    business_name: str, cutoff: date, successful_runs: list[dict]
) -> list[tuple[date, date]]:
    return [
        (start, end)
        for start, end in live_windows(cutoff)
        if not _covered_by_successful_runs(
            successful_runs, business_name, "live", start, end
        )
    ]


async def successful_live_runs(database, shop, business_name: str) -> list[dict]:
    async with database.system_session_factory() as session:
        rows = (
            await session.scalars(
                select(AnalyticsSyncRun).where(
                    AnalyticsSyncRun.tenant_id == shop.tenant_id,
                    AnalyticsSyncRun.shop_id == shop.shop_id,
                    AnalyticsSyncRun.resource_type == "live",
                    AnalyticsSyncRun.account_type == "AFFILIATE_ACCOUNTS",
                    AnalyticsSyncRun.status == "succeeded",
                )
            )
        ).all()
    zone = ZoneInfo(shop.timezone)
    return [
        {
            "shop": business_name,
            "resource": "live",
            "window": (
                row.window_start.astimezone(zone).date(),
                row.window_end.astimezone(zone).date() - timedelta(days=1),
            ),
            "status": row.status,
            "fetched": row.fetched_count,
            "persisted": row.persisted_count,
            "finished_at": row.finished_at,
        }
        for row in rows
        if row.window_start and row.window_end
    ]


async def plan_next(database, redis, now: datetime):
    if not daily_collection_window_open(now):
        return None, "outside_collection_window"
    shops = [
        shop for shop in await _active_live_shops(database)
        if shop.tenant_id == get_settings().affiliate_export_tenant_id
        and shop.source_name in BUSINESS_NAMES
    ]
    if len(shops) != len(TARGET_SHOPS) or {
        shop.source_name for shop in shops
    } != set(BUSINESS_NAMES):
        return None, "five_shop_identity_incomplete"
    health_repository = AffiliateCaptureHealthRepository(redis)
    for shop in shops:
        health = await health_repository.get(shop.tenant_id, shop.shop_id)
        if health.state != "online" or not health.session_available:
            continue
        if not await sample_round_releases_affiliate(
            database, shop.tenant_id, shop.shop_id, now=now
        ):
            continue
        recent = await latest_recent_live_observation(
            database, shop.tenant_id, shop.shop_id, now=now
        )
        if recent is None:
            persisted = await latest_persisted_live_date(
                database, shop.tenant_id, shop.shop_id
            )
            if persisted is not None:
                return (shop, "probe", persisted, persisted), "ready"
            continue
        missing = missing_windows(
            BUSINESS_NAMES[shop.source_name], recent[0],
            await successful_live_runs(
                database, shop, BUSINESS_NAMES[shop.source_name]
            ),
        )
        if missing:
            start, end = missing[0]
            return (shop, "window", start, end), "ready"
    return None, "no_due_live_work"


async def execute_one(database, redis, service, plan, now: datetime) -> str:
    shop, kind, start, end = plan
    owner = uuid4().hex
    lock = f"affiliate:auto-live:lock:{shop.shop_id}"
    if not await redis.set(lock, owner, nx=True, ex=3600):
        return "shop_locked"
    try:
        zone = ZoneInfo(shop.timezone)
        start_at = datetime.combine(start, time.min, zone).astimezone(UTC)
        end_at = datetime.combine(end + timedelta(days=1), time.min, zone).astimezone(UTC)
        batch_date = latest_due_schedule_date(now)
        job_id = (
            f"auto-affiliate-live:{batch_date:%Y%m%d}:{shop.shop_id}:"
            f"{kind}:{start:%Y%m%d}-{end:%Y%m%d}:{uuid4().hex}"
        )
        ctx = {
            "database": database, "redis": redis,
            "analytics_sync_service": service,
            "analytics_sync_max_tries": get_settings().tiktok_analytics_job_max_tries,
            "job_id": job_id, "job_try": 1,
        }
        result = await sync_analytics_job(
            ctx, str(shop.tenant_id), str(shop.shop_id), "live",
            start_at.isoformat(), end_at.isoformat(), shop.currency,
            "AFFILIATE_ACCOUNTS", "official_api",
        )
        if result is None or result.status != "succeeded":
            raise RuntimeError("Official live sync did not succeed")
        if result.fetched_count != result.persisted_count:
            raise RuntimeError("Official live fetched and persisted totals differ")
        return (
            f"stored shop={BUSINESS_NAMES[shop.source_name]} kind={kind} "
            f"window={start}..{end} fetched={result.fetched_count}"
        )
    finally:
        await redis.eval(UNLOCK_IF_OWNED, 1, lock, owner)


async def run(args) -> None:
    load_analytics_config(args.config)
    settings = get_settings()
    database = Database(settings.database_url)
    redis = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    try:
        from erp_api.main import build_analytics_services

        service = build_analytics_services(
            settings, database, redis_client=redis
        )["analytics_sync_service"]
        if service is None:
            raise RuntimeError("Official analytics service is unavailable")
        while True:
            try:
                plan, reason = await plan_next(database, redis, datetime.now(UTC))
                if plan is not None and not args.dry_run:
                    reason = await execute_one(
                        database, redis, service, plan, datetime.now(UTC)
                    )
                elif plan is not None:
                    reason = (
                        f"due shop={BUSINESS_NAMES[plan[0].source_name]} "
                        f"kind={plan[1]} window={plan[2]}..{plan[3]}"
                    )
                print(f"AUTO_LIVE {reason}", flush=True)
            except Exception as error:
                print(f"AUTO_LIVE_FAILED type={type(error).__name__}", flush=True)
                if args.once:
                    raise
            if args.once:
                return
            await asyncio.sleep(args.interval_seconds)
    finally:
        await redis.aclose()
        await database.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--interval-seconds", type=float, default=180)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.interval_seconds < 60:
        parser.error("Interval must be at least 60 seconds")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
