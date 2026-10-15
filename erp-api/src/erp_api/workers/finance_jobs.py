from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select

from erp_api.models.shop import Shop
from erp_api.models.shop_connection import ShopConnection
from erp_api.models.tenant import Tenant


async def sync_finance_job(
    ctx,
    tenant_id: str,
    shop_id: str,
    mode: str = "incremental",
    window_from: str | None = None,
    window_to: str | None = None,
    trigger: str = "scheduled",
):
    service = ctx.get("finance_sync_service")
    if service is None:
        return None
    result = await service.sync(
        UUID(tenant_id),
        shop_id=UUID(shop_id),
        mode=mode,
        window_from=datetime.fromisoformat(window_from) if window_from else None,
        window_to=datetime.fromisoformat(window_to) if window_to else None,
        trigger=trigger,
        attempt=max(1, int(ctx.get("job_try", 1))),
        max_attempts=max(1, int(ctx.get("finance_sync_max_tries", 5))),
    )
    if result.status == "retry_wait":
        raise RuntimeError(
            "Finance sync failed; see the tenant-scoped sync run for its safe summary."
        )
    return result


async def enqueue_scheduled_finance_syncs(ctx) -> int:
    now = _now(ctx)
    redis = ctx["redis"]
    shops = await _authorized_shops(ctx["database"])
    for tenant_id, shop_id in shops:
        await redis.enqueue_job(
            "sync_finance_job",
            str(tenant_id),
            str(shop_id),
            "incremental",
            _job_id=f"finance-sync:{shop_id}:{now:%Y%m%d%H%M}",
        )
    return len(shops)


async def _authorized_shops(database) -> list[tuple[UUID, UUID]]:
    async with database.system_session_factory() as session:
        tenant_ids = (await session.scalars(select(Tenant.id))).all()
    shops: list[tuple[UUID, UUID]] = []
    for tenant_id in tenant_ids:
        async for session in database.session(tenant_id):
            ids = (
                await session.scalars(
                    select(Shop.id)
                    .join(ShopConnection, ShopConnection.shop_id == Shop.id)
                    .where(
                        Shop.platform == "tiktok",
                        ShopConnection.auth_status == "authorized",
                    )
                )
            ).all()
            shops.extend((tenant_id, shop_id) for shop_id in ids)
    return shops


def _now(ctx) -> datetime:
    clock = ctx.get("clock")
    value = clock() if callable(clock) else datetime.now(UTC)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Finance worker clock must include a UTC offset.")
    return value.astimezone(UTC)
