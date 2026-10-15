from __future__ import annotations

from uuid import UUID

from arq import Retry

from erp_api.services.sample_notification_order import (
    sync_assignment_record_and_deliver,
)
from erp_api.services.sample_notification_service import SampleNotificationResult


async def send_sample_notification_job(ctx, tenant_id: str, event_id: str):
    notifications = ctx.get("sample_notification_service")
    if notifications is None:
        raise RuntimeError("Sample notification service is unavailable.")
    lock = ctx.get("sample_shop_sync_lock")
    if lock is None:
        raise RuntimeError("Sample shop sync lock is unavailable.")
    parsed_tenant_id = UUID(tenant_id)
    parsed_event_id = UUID(event_id)
    shop_id = await notifications.shop_id_for_event(parsed_tenant_id, parsed_event_id)
    if shop_id is None:
        return SampleNotificationResult(parsed_event_id, "skipped")
    async with lock.acquire(parsed_tenant_id, shop_id) as acquired:
        if not acquired:
            raise Retry(defer=ctx.get("sample_shop_lock_retry_seconds", 30))
        if await notifications.shop_id_for_event(parsed_tenant_id, parsed_event_id) != shop_id:
            return SampleNotificationResult(parsed_event_id, "skipped")
        assignment_records = ctx.get("sample_assignment_record_service")
        if assignment_records is None:
            raise RuntimeError("Sample assignment record service is unavailable.")
        result, _assignment_result = await sync_assignment_record_and_deliver(
            notifications,
            assignment_records,
            tenant_id=parsed_tenant_id,
            shop_id=shop_id,
            event_id=parsed_event_id,
        )
        return result
