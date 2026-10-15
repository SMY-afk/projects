"""Queue shop-scoped affiliate live coverage after sample collection."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from arq.constants import default_queue_name
from dateutil.relativedelta import relativedelta
from sqlalchemy import select

from erp_api.models.shop import Shop
from erp_api.models.shop_connection import ShopConnection
from erp_api.services.affiliate_capture_health import AffiliateCaptureHealthRepository
from erp_api.services.affiliate_sample_priority import sample_round_releases_affiliate
from erp_api.services.affiliate_schedule_coordination import TARGET_AFFILIATE_SHOP_NAMES
from erp_api.services.affiliate_schedule_queries import (
    ScheduledShop,
    daily_collection_window_open,
    latest_due_schedule_date,
)
from erp_api.workers.affiliate_live_observation import (
    latest_persisted_live_date,
    latest_recent_live_observation,
)
from erp_api.workers.analytics_jobs import _now

LIVE_CHUNK_DAYS = 30


def live_windows(cutoff: date) -> list[tuple[date, date]]:
    start = cutoff - relativedelta(months=2)
    windows = []
    while start <= cutoff:
        end = min(start + timedelta(days=LIVE_CHUNK_DAYS - 1), cutoff)
        windows.append((start, end))
        start = end + timedelta(days=1)
    return windows


async def enqueue_scheduled_affiliate_live_syncs(ctx) -> int:
    now = _now(ctx)
    if not daily_collection_window_open(now):
        return 0
    database = ctx["database"]
    redis = ctx["redis"]
    health_repository = AffiliateCaptureHealthRepository(redis)
    batch_date = latest_due_schedule_date(now)
    queued = 0
    for shop in await _active_live_shops(database):
        health = await health_repository.get(shop.tenant_id, shop.shop_id)
        if health.state != "online" or not health.session_available:
            continue
        cutoff = await health_repository.observed_date_for(
            shop.tenant_id, shop.shop_id, "liveAccounts"
        )
        if cutoff is None:
            recent = await latest_recent_live_observation(
                database, shop.tenant_id, shop.shop_id, now=now
            )
            cutoff = recent[0] if recent else None
        if not await sample_round_releases_affiliate(
            database, shop.tenant_id, shop.shop_id, now=now
        ):
            continue
        if cutoff is None:
            persisted = await latest_persisted_live_date(
                database, shop.tenant_id, shop.shop_id
            )
            if persisted is not None:
                queued += await _enqueue_live_probe(redis, shop, batch_date, persisted, now)
            continue
        if cutoff > now.astimezone(ZoneInfo(shop.timezone)).date():
            continue
        for start, end in live_windows(cutoff):
            key = (
                f"affiliate:live-batch:{batch_date:%Y%m%d}:{shop.shop_id}:"
                f"{cutoff:%Y%m%d}:{start:%Y%m%d}-{end:%Y%m%d}"
            )
            if not await redis.set(key, "1", ex=86_400, nx=True):
                continue
            zone = ZoneInfo(shop.timezone)
            window_start = datetime.combine(start, time.min, zone).astimezone(UTC)
            window_end = datetime.combine(
                end + timedelta(days=1), time.min, zone
            ).astimezone(UTC)
            try:
                job = await redis.enqueue_job(
                    "sync_analytics_job",
                    str(shop.tenant_id),
                    str(shop.shop_id),
                    "live",
                    window_start.isoformat(),
                    window_end.isoformat(),
                    shop.currency,
                    "AFFILIATE_ACCOUNTS",
                    source_kind="official_api",
                    _job_id=key,
                    _queue_name=default_queue_name,
                )
            except Exception:
                await redis.delete(key)
                raise
            if job is None:
                continue
            queued += 1
    return queued


async def _enqueue_live_probe(redis, shop, batch_date: date, cutoff: date, now: datetime) -> int:
    """Refresh the official overview date without treating the old day as evidence."""
    bucket = f"{now:%Y%m%d%H}{now.minute // 10}"
    key = f"affiliate:live-probe:{batch_date:%Y%m%d}:{shop.shop_id}:{bucket}"
    if not await redis.set(key, "1", ex=86_400, nx=True):
        return 0
    zone = ZoneInfo(shop.timezone)
    start = datetime.combine(cutoff, time.min, zone).astimezone(UTC)
    end = datetime.combine(cutoff + timedelta(days=1), time.min, zone).astimezone(UTC)
    try:
        job = await redis.enqueue_job(
            "sync_analytics_job",
            str(shop.tenant_id), str(shop.shop_id), "live",
            start.isoformat(), end.isoformat(), shop.currency,
            "AFFILIATE_ACCOUNTS", source_kind="official_api", _job_id=key,
            _queue_name=default_queue_name,
        )
    except Exception:
        await redis.delete(key)
        raise
    if job is None:
        await redis.delete(key)
        return 0
    return 1


async def _active_live_shops(database) -> list[ScheduledShop]:
    async with database.system_session_factory() as session:
        rows = (
            await session.execute(
                select(
                    Shop.tenant_id,
                    Shop.id,
                    Shop.timezone,
                    Shop.currency,
                    Shop.shop_name,
                    ShopConnection.auth_status,
                )
                .join(ShopConnection, ShopConnection.shop_id == Shop.id)
                .where(
                    Shop.platform == "tiktok",
                    Shop.status == "active",
                    Shop.shop_name.in_(TARGET_AFFILIATE_SHOP_NAMES),
                    Shop.timezone.is_not(None),
                )
            )
        ).all()
    return [
        ScheduledShop(tenant_id, shop_id, timezone, currency or "USD", name)
        for tenant_id, shop_id, timezone, currency, name, auth in rows
        if auth == "authorized"
    ]
