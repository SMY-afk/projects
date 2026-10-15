from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select

from erp_api.models.shop import Shop
from erp_api.models.shop_connection import ShopConnection
from erp_api.models.tenant import Tenant
from erp_api.services.analytics_resource_types import require_arq_official_resource
from erp_api.services.video_ranges import resolve_video_range
from erp_api.workers.affiliate_live_observation import record_completed_live_date


async def sync_analytics_job(
    ctx,
    tenant_id: str,
    shop_id: str,
    resource_type: str,
    window_start: str | None = None,
    window_end: str | None = None,
    currency: str = "USD",
    account_type: str = "ALL",
    source_kind: str = "official_api",
):
    resource_type = require_arq_official_resource(resource_type, source_kind)
    service = ctx["analytics_sync_service"]
    if service is None:
        return None
    result = await service.sync(
        UUID(tenant_id),
        shop_id=UUID(shop_id),
        resource_type=resource_type,
        job_id=ctx.get("job_id") or f"analytics-sync:{shop_id}:{resource_type}",
        attempt=max(1, int(ctx.get("job_try", 1))),
        max_attempts=ctx["analytics_sync_max_tries"],
        window_start=datetime.fromisoformat(window_start) if window_start else None,
        window_end=datetime.fromisoformat(window_end) if window_end else None,
        currency=currency,
        account_type=account_type,
    )
    if result is not None and result.status == "retry_wait":
        raise RuntimeError(
            "Analytics sync failed; see the tenant-scoped sync run for its safe summary."
        )
    if resource_type == "live" and account_type == "AFFILIATE_ACCOUNTS":
        await record_completed_live_date(ctx, UUID(tenant_id), result)
    return result


async def enqueue_scheduled_analytics_syncs(ctx) -> int:
    redis = ctx["redis"]
    now = _now(ctx)
    queued = 0
    for tenant_id, shop_id, shop_timezone in await _authorized_shops(ctx["database"]):
        for preset in ("last7d", "last30d"):
            resolved = resolve_video_range(
                preset=preset,
                shop_timezone=shop_timezone,
                now=now,
            )
            await _enqueue_video_window(
                redis,
                tenant_id,
                shop_id,
                resolved.window_start,
                resolved.window_end,
                refresh_key=now.strftime("%Y%m%d"),
            )
            queued += 1
        await redis.enqueue_job(
            "sync_analytics_job",
            str(tenant_id),
            str(shop_id),
            "live",
            source_kind="official_api",
            _job_id=f"analytics-sync:{shop_id}:live:{now:%Y%m%d}",
        )
        queued += 1
        affiliate_live = resolve_video_range(
            preset="last7d",
            shop_timezone=shop_timezone,
            now=now,
        )
        await _enqueue_affiliate_live_window(
            redis,
            tenant_id,
            shop_id,
            affiliate_live.window_start,
            affiliate_live.window_end,
            refresh_key=now.strftime("%Y%m%d"),
        )
        queued += 1
    return queued


async def enqueue_hourly_video_syncs(ctx) -> int:
    redis = ctx["redis"]
    now = _now(ctx)
    queued = 0
    for tenant_id, shop_id, shop_timezone in await _authorized_shops(ctx["database"]):
        resolved = resolve_video_range(
            preset="today",
            shop_timezone=shop_timezone,
            now=now,
        )
        await _enqueue_video_window(
            redis,
            tenant_id,
            shop_id,
            resolved.window_start,
            resolved.window_end,
            refresh_key=now.strftime("%Y%m%d%H"),
        )
        queued += 1
    return queued


async def _authorized_shops(database) -> list[tuple[UUID, UUID, str]]:
    async with database.system_session_factory() as session:
        tenant_ids = (await session.scalars(select(Tenant.id))).all()
    shops = []
    for tenant_id in tenant_ids:
        async for session in database.session(tenant_id):
            rows = (
                await session.execute(
                    select(Shop.id, Shop.timezone)
                    .join(ShopConnection, ShopConnection.shop_id == Shop.id)
                    .where(
                        Shop.platform == "tiktok",
                        ShopConnection.auth_status == "authorized",
                        Shop.timezone.is_not(None),
                    )
                )
            ).all()
            shops.extend((tenant_id, shop_id, timezone) for shop_id, timezone in rows)
    return shops


async def _enqueue_video_window(
    redis,
    tenant_id: UUID,
    shop_id: UUID,
    window_start: datetime,
    window_end: datetime,
    *,
    refresh_key: str,
) -> None:
    await redis.enqueue_job(
        "sync_analytics_job",
        str(tenant_id),
        str(shop_id),
        "video",
        window_start.isoformat(),
        window_end.isoformat(),
        "USD",
        "ALL",
        source_kind="official_api",
        _job_id=video_window_job_id(
            shop_id,
            window_start,
            window_end,
            currency="USD",
            account_type="ALL",
            refresh_key=refresh_key,
        ),
    )


async def _enqueue_affiliate_live_window(
    redis,
    tenant_id: UUID,
    shop_id: UUID,
    window_start: datetime,
    window_end: datetime,
    *,
    refresh_key: str,
) -> None:
    await redis.enqueue_job(
        "sync_analytics_job",
        str(tenant_id),
        str(shop_id),
        "live",
        window_start.isoformat(),
        window_end.isoformat(),
        "USD",
        "AFFILIATE_ACCOUNTS",
        source_kind="official_api",
        _job_id=(
            f"analytics-sync:{shop_id}:live-affiliate:"
            f"{window_start:%Y%m%d}:{window_end:%Y%m%d}:{refresh_key}"
        ),
    )


def video_window_job_id(
    shop_id: UUID,
    window_start: datetime,
    window_end: datetime,
    *,
    currency: str,
    account_type: str,
    refresh_key: str,
) -> str:
    return (
        f"analytics-sync:{shop_id}:video:{window_start:%Y%m%d}:"
        f"{window_end:%Y%m%d}:{currency}:{account_type}:{refresh_key}"
    )


def _now(ctx) -> datetime:
    clock = ctx.get("clock")
    value = clock() if callable(clock) else datetime.now(UTC)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Analytics worker clock must include a UTC offset.")
    return value.astimezone(UTC)


async def purge_analytics_raw_payloads_job(ctx) -> int:
    database = ctx["database"]
    repository = ctx["analytics_sync_repository"]
    bestseller_repository = ctx.get("bestseller_repository")
    async with database.system_session_factory() as session:
        tenant_ids = (await session.scalars(select(Tenant.id))).all()
    removed = 0
    for tenant_id in tenant_ids:
        removed += await repository.purge_expired_raw_payloads(tenant_id)
        if bestseller_repository is not None:
            removed += await bestseller_repository.clear_expired_raw_payloads(tenant_id)
    return removed
