from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select

from erp_api.models.shop import Shop
from erp_api.models.shop_connection import ShopConnection
from erp_api.models.tenant import Tenant


async def sync_product_job(ctx, tenant_id: str, shop_id: str):
    service = ctx["product_sync_service"]
    if service is None:
        return None
    return await service.sync_products(UUID(tenant_id), shop_id=UUID(shop_id))


async def enqueue_scheduled_product_syncs(ctx) -> int:
    database = ctx["database"]
    redis = ctx["redis"]
    now = _now(ctx)
    async with database.system_session_factory() as session:
        tenant_ids = (await session.scalars(select(Tenant.id))).all()
    queued = 0
    for tenant_id in tenant_ids:
        async for session in database.session(tenant_id):
            shop_ids = (
                await session.scalars(
                    select(Shop.id)
                    .join(ShopConnection, ShopConnection.shop_id == Shop.id)
                    .where(
                        Shop.platform == "tiktok",
                        ShopConnection.auth_status == "authorized",
                    )
                )
            ).all()
        for shop_id in shop_ids:
            await redis.enqueue_job(
                "sync_product_job",
                str(tenant_id),
                str(shop_id),
                _job_id=scheduled_product_job_id(tenant_id, shop_id, now),
            )
            queued += 1
    return queued


def scheduled_product_job_id(
    tenant_id: UUID, shop_id: UUID, now: datetime
) -> str:
    utc_now = _as_utc(now)
    slot = utc_now.replace(minute=0, second=0, microsecond=0)
    return f"product-sync:{tenant_id}:{shop_id}:{slot:%Y%m%d%H}"


def _now(ctx) -> datetime:
    clock = ctx.get("clock")
    return _as_utc(clock() if callable(clock) else datetime.now(UTC))


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Product worker clock must include a UTC offset.")
    return value.astimezone(UTC)
