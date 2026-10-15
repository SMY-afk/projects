from __future__ import annotations

import random
import re
from datetime import UTC, datetime
from uuid import UUID

from arq import Retry
from sqlalchemy import select

from erp_api.models.shop import Shop
from erp_api.models.shop_connection import ShopConnection
from erp_api.models.tenant import Tenant
from erp_api.services.tiktok_transport import (
    TikTokApiError,
    TikTokClientError,
    TikTokRateLimitError,
)


async def sync_order_job(ctx, tenant_id: str, shop_id: str, trigger: str = "scheduled"):
    service = ctx["order_sync_service"]
    try:
        result = await service.sync_orders(
            UUID(tenant_id), shop_id=UUID(shop_id), trigger=trigger, mode="incremental"
        )
    except TikTokClientError as error:
        if isinstance(error, TikTokApiError) and not (
            isinstance(error, TikTokRateLimitError)
            or error.upstream_status_code in {429, 500, 502, 503, 504}
        ):
            raise
        delay = getattr(error, "retry_after_seconds", None)
        raise Retry(defer=max(1.0, delay if delay is not None else
                              retry_delay(ctx.get("job_try", 1)))) from error
    if result.status == "failed" and _transient_failure(result.error or ""):
        raise Retry(defer=max(1.0, retry_delay(ctx.get("job_try", 1))))
    return result


def _transient_failure(summary: str) -> bool:
    if summary.startswith(("TikTokTimeoutError:", "TikTokClientError:",
                           "TikTokRateLimitError ")):
        return True
    return bool(re.match(
        r"^TikTokApiError code=http_(?:429|500|502|503|504)\s", summary
    ))


async def process_order_webhook_job(ctx, tenant_id: str, event_id: str):
    tenant_uuid = UUID(tenant_id)
    event_uuid = UUID(event_id)
    webhook_service = ctx["webhook_service"]
    event = await webhook_service.get_event(tenant_uuid, event_uuid)
    if event is None:
        return None
    try:
        result = await sync_order_job(ctx, tenant_id, str(event.shop_id), "webhook")
        status = "succeeded" if result.status == "succeeded" else "failed"
        await webhook_service.finish_event(
            tenant_uuid,
            event_uuid,
            status=status,
            error_summary=result.error,
        )
        return result
    except Exception as error:
        await webhook_service.finish_event(
            tenant_uuid,
            event_uuid,
            status="failed",
            error_summary=f"{type(error).__name__}: webhook order sync failed"[:1000],
        )
        raise


async def enqueue_scheduled_order_syncs(ctx):
    database = ctx["database"]
    redis = ctx["redis"]
    now = _now(ctx)
    async with database.system_session_factory() as session:
        tenants = (await session.scalars(select(Tenant.id))).all()
    queued = 0
    for tenant_id in tenants:
        async for session in database.session(tenant_id):
            shops = (
                await session.scalars(
                    select(Shop.id)
                    .join(ShopConnection, ShopConnection.shop_id == Shop.id)
                    .where(
                        Shop.platform == "tiktok",
                        ShopConnection.auth_status == "authorized",
                    )
                )
            ).all()
        for shop_id in shops:
            await redis.enqueue_job(
                "sync_order_job",
                str(tenant_id),
                str(shop_id),
                "scheduled",
                _job_id=scheduled_order_job_id(tenant_id, shop_id, now),
            )
            queued += 1
    return queued


async def purge_order_pii_job(ctx):
    database = ctx["database"]
    repository = ctx["order_repository"]
    async with database.system_session_factory() as session:
        tenants = (await session.scalars(select(Tenant.id))).all()
    return sum([await repository.purge_expired_pii(tenant_id) for tenant_id in tenants])


def retry_delay(attempt: int) -> float:
    return random.uniform(0, min(1800, 30 * (2 ** max(0, attempt - 1))))


def scheduled_order_job_id(
    tenant_id: UUID, shop_id: UUID, now: datetime
) -> str:
    utc_now = _as_utc(now)
    slot = utc_now.replace(
        minute=(utc_now.minute // 10) * 10,
        second=0,
        microsecond=0,
    )
    return f"order-sync:{tenant_id}:{shop_id}:{slot:%Y%m%d%H%M}"


def _now(ctx) -> datetime:
    clock = ctx.get("clock")
    return _as_utc(clock() if callable(clock) else datetime.now(UTC))


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Order worker clock must include a UTC offset.")
    return value.astimezone(UTC)
