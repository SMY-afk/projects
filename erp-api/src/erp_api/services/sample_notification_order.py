from __future__ import annotations

from uuid import UUID


async def sync_assignment_record_and_deliver(
    notifications,
    assignment_records,
    *,
    tenant_id: UUID,
    shop_id: UUID,
    event_id: UUID,
):
    scope = {
        "tenant_id": tenant_id,
        "shop_id": shop_id,
        "outbox_ids": frozenset({event_id}),
    }
    await assignment_records.sync(**scope)
    notification_result = await notifications.deliver(tenant_id, event_id)
    assignment_result = await assignment_records.sync(**scope)
    return notification_result, assignment_result
