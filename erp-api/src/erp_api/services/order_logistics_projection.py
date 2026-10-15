from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from erp_api.models.logistics_task import LogisticsTask
from erp_api.models.logistics_task_operation import LogisticsTaskOperation
from erp_api.models.order import Order
from erp_api.models.user import User
from erp_api.services.tiktok_platform_logistics_sync_persistence import (
    create_task,
    ensure_task_items,
)
from erp_api.services.tiktok_platform_logistics_sync_records import merge_task_status

ELIGIBLE_ORDER_STATUSES = {
    "awaiting_shipment",
    "awaiting_collection",
    "in_transit",
    "delivered",
}


async def project_order_to_logistics(
    session,
    tenant_id: UUID,
    order_id: UUID,
) -> None:
    order = await session.scalar(
        select(Order)
        .options(selectinload(Order.lines))
        .where(Order.id == order_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if order is None:
        return
    task = await session.scalar(
        select(LogisticsTask)
        .options(
            selectinload(LogisticsTask.items),
            selectinload(LogisticsTask.operations),
        )
        .where(
            LogisticsTask.order_id == order.id,
            LogisticsTask.source_type == "sales_order",
            LogisticsTask.status != "cancelled",
        )
        .order_by(LogisticsTask.created_at, LogisticsTask.id)
        .limit(1)
        .with_for_update()
    )
    if task is None and order.status not in ELIGIBLE_ORDER_STATUSES:
        return

    actor_id = task.created_by_user_id if task is not None else None
    if actor_id is None:
        actor_id = await session.scalar(
            select(User.id).where(User.status == "active").order_by(User.created_at)
        )
    if actor_id is None:
        raise ValueError("Order logistics projection requires an active user.")

    created = task is None
    if task is None:
        task = create_task(tenant_id, order, actor_id)
        session.add(task)
        await session.flush()
    else:
        ensure_task_items(tenant_id, task, order)

    previous_status = None if created else task.status
    task.status = merge_task_status(task.status, order.external_status)
    _align_item_quantities(task, order)
    task.updated_at = datetime.now(UTC)
    if created or previous_status != task.status:
        task.operations.append(
            LogisticsTaskOperation(
                tenant_id=tenant_id,
                operation_type="order_sync_projected",
                from_status=previous_status,
                to_status=task.status,
                actor_user_id=actor_id,
                note="Projected from the latest TikTok order status.",
                details={
                    "orderStatus": order.status,
                    "externalStatus": order.external_status,
                },
            )
        )


def _align_item_quantities(task: LogisticsTask, order: Order) -> None:
    quantities = {line.id: line.quantity for line in order.lines}
    for item in task.items:
        item.planned_quantity = max(
            item.planned_quantity,
            quantities.get(item.order_line_id, item.planned_quantity),
        )
        if task.status == "pending_dispatch":
            item.packed_quantity = item.planned_quantity
            item.shipped_quantity = item.shipped_quantity or 0
        elif task.status in {"shipped", "in_transit", "delivered"}:
            item.packed_quantity = item.planned_quantity
            item.shipped_quantity = item.planned_quantity
