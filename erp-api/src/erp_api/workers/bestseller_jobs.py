from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from arq import Retry
from sqlalchemy import select

from erp_api.models.shop import Shop
from erp_api.models.shop_connection import ShopConnection
from erp_api.models.tenant import Tenant
from erp_api.services.bestseller_sync_service import BestsellerSyncError

ENTITY_TYPES = ("product", "creator", "video", "live")
TIME_SLOTS = ("1D", "7D", "30D")


async def sync_bestseller_job(
    ctx,
    tenant_id: str,
    shop_id: str,
    entity_type: str,
    reference_date: str,
    time_slot: str,
    currency: str = "USD",
    author_type: str | None = None,
):
    service = ctx["bestseller_sync_service"]
    if service is None:
        return None
    try:
        return await service.sync(
            UUID(tenant_id),
            shop_id=UUID(shop_id),
            entity_type=entity_type,
            reference_date=date.fromisoformat(reference_date),
            time_slot=time_slot,
            currency=currency,
            author_type=author_type,
        )
    except BestsellerSyncError as error:
        if error.retryable:
            defer = (
                error.retry_after_seconds
                if error.retry_after_seconds is not None
                else 30
            )
            raise Retry(defer=defer) from error
        return {
            "status": "failed",
            "errorCategory": error.category,
            "retryable": False,
            "snapshotMarkedStale": error.snapshot_marked_stale,
        }


async def enqueue_scheduled_bestseller_syncs(ctx) -> int:
    redis = ctx["redis"]
    now = _now(ctx)
    queued = 0
    for tenant_id, shop_id, timezone in await _authorized_shops(ctx["database"]):
        reference_date = now.astimezone(ZoneInfo(timezone)).date() - timedelta(days=1)
        for entity_type in ENTITY_TYPES:
            author_type = "ALL" if entity_type == "creator" else None
            for time_slot in TIME_SLOTS:
                await redis.enqueue_job(
                    "sync_bestseller_job",
                    str(tenant_id),
                    str(shop_id),
                    entity_type,
                    reference_date.isoformat(),
                    time_slot,
                    "USD",
                    author_type,
                    _job_id=bestseller_job_id(
                        tenant_id,
                        shop_id,
                        entity_type=entity_type,
                        reference_date=reference_date,
                        time_slot=time_slot,
                        currency="USD",
                        author_type=author_type,
                    ),
                )
                queued += 1
    return queued


def bestseller_job_id(
    tenant_id: UUID,
    shop_id: UUID,
    *,
    entity_type: str,
    reference_date: date,
    time_slot: str,
    currency: str,
    author_type: str | None,
) -> str:
    return (
        f"bestseller-sync:{tenant_id}:{shop_id}:{entity_type}:"
        f"{reference_date:%Y%m%d}:"
        f"{time_slot}:{currency}:{author_type or 'NONE'}"
    )


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


def _now(ctx) -> datetime:
    clock = ctx.get("clock")
    value = clock() if callable(clock) else datetime.now(UTC)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Bestseller scheduler clock must include a UTC offset.")
    return value.astimezone(UTC)
