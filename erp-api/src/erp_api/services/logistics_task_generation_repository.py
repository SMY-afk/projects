from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from erp_api.infrastructure.database import Database
from erp_api.models.logistics_task import LogisticsTask
from erp_api.models.logistics_task_item import LogisticsTaskItem
from erp_api.models.logistics_task_operation import LogisticsTaskOperation
from erp_api.models.order import Order
from erp_api.services.logistics_records import task_record
from erp_api.services.logistics_repository import (
    LogisticsSourceNotFoundError,
    LogisticsTaskConflictError,
    LogisticsTaskValidationError,
)


@dataclass(frozen=True)
class LogisticsTaskPlanItemInput:
    order_line_id: UUID
    planned_quantity: int


@dataclass(frozen=True)
class LogisticsTaskPlanInput:
    items: list[LogisticsTaskPlanItemInput]
    priority: str
    note: str | None


class LogisticsTaskGenerationRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def generate_sales_order_tasks(
        self,
        tenant_id: UUID,
        *,
        actor_user_id: UUID,
        order_id: UUID,
        plans: list[LogisticsTaskPlanInput],
    ) -> list[dict[str, object]]:
        _validate_plans(plans)
        line_ids = [item.order_line_id for plan in plans for item in plan.items]
        async for session in self._database.session(tenant_id):
            order = await session.scalar(
                select(Order)
                .options(selectinload(Order.lines))
                .where(Order.id == order_id)
                .with_for_update()
            )
            if order is None:
                raise LogisticsSourceNotFoundError("Sales order was not found.")
            order_lines = {line.id: line for line in order.lines}
            requested = _requested_quantities(plans)
            if requested.keys() - order_lines.keys():
                raise LogisticsTaskValidationError(
                    "A selected order line does not belong to the sales order."
                )
            existing_planned = await _planned_quantities(session, order_id, line_ids)
            for line_id, quantity in requested.items():
                if quantity > order_lines[line_id].quantity - existing_planned.get(
                    line_id, 0
                ):
                    raise LogisticsTaskConflictError(
                        "Planned quantity exceeds the unassigned order quantity."
                    )
            tasks = [
                _build_task(
                    tenant_id,
                    actor_user_id=actor_user_id,
                    order=order,
                    order_lines=order_lines,
                    plan=plan,
                    batch_index=index,
                )
                for index, plan in enumerate(plans)
            ]
            session.add_all(tasks)
            await session.commit()
            stored = await session.scalars(
                select(LogisticsTask)
                .options(
                    selectinload(LogisticsTask.items),
                    selectinload(LogisticsTask.operations),
                    selectinload(LogisticsTask.reviews),
                )
                .where(LogisticsTask.id.in_([task.id for task in tasks]))
                .execution_options(populate_existing=True)
            )
            by_id = {task.id: task for task in stored.unique().all()}
            return [task_record(by_id[task.id]) for task in tasks]
        raise RuntimeError("Tenant database session was not created.")


def _validate_plans(plans: list[LogisticsTaskPlanInput]) -> None:
    if not plans:
        raise LogisticsTaskValidationError("At least one task plan is required.")
    for plan in plans:
        if not plan.items:
            raise LogisticsTaskValidationError("Each task plan requires order lines.")
        if len({item.order_line_id for item in plan.items}) != len(plan.items):
            raise LogisticsTaskValidationError(
                "An order line can appear only once in one task plan."
            )
        if any(item.planned_quantity < 1 for item in plan.items):
            raise LogisticsTaskValidationError("Planned quantity must be positive.")


def _requested_quantities(
    plans: list[LogisticsTaskPlanInput],
) -> dict[UUID, int]:
    quantities: defaultdict[UUID, int] = defaultdict(int)
    for plan in plans:
        for item in plan.items:
            quantities[item.order_line_id] += item.planned_quantity
    return dict(quantities)


async def _planned_quantities(session, order_id: UUID, line_ids: list[UUID]):
    rows = await session.execute(
        select(
            LogisticsTaskItem.order_line_id,
            func.sum(LogisticsTaskItem.planned_quantity),
        )
        .join(LogisticsTask, LogisticsTask.id == LogisticsTaskItem.task_id)
        .where(
            LogisticsTask.order_id == order_id,
            LogisticsTask.status != "cancelled",
            LogisticsTaskItem.order_line_id.in_(set(line_ids)),
        )
        .group_by(LogisticsTaskItem.order_line_id)
    )
    return {line_id: int(quantity) for line_id, quantity in rows}


def _build_task(
    tenant_id: UUID,
    *,
    actor_user_id: UUID,
    order: Order,
    order_lines,
    plan: LogisticsTaskPlanInput,
    batch_index: int,
) -> LogisticsTask:
    task = LogisticsTask(
        tenant_id=tenant_id,
        task_number=f"LT-{datetime.now(UTC):%Y%m%d}-{uuid4().hex[:10].upper()}",
        source_type="sales_order",
        source_reference_id=order.id,
        source_number=order.order_number,
        order_id=order.id,
        shop_id=order.shop_id,
        priority=plan.priority,
        status="pending_review",
        note=plan.note,
        created_by_user_id=actor_user_id,
    )
    for item in plan.items:
        line = order_lines[item.order_line_id]
        task.items.append(
            LogisticsTaskItem(
                tenant_id=tenant_id,
                source_line_id=line.id,
                order_line_id=line.id,
                platform_product_id=line.platform_product_id,
                platform_sku_id=line.platform_sku_id,
                seller_sku=line.seller_sku,
                product_name=line.product_name,
                sku_name=line.sku_name,
                planned_quantity=item.planned_quantity,
                packed_quantity=0,
                shipped_quantity=0,
            )
        )
    task.operations.append(
        LogisticsTaskOperation(
            tenant_id=tenant_id,
            operation_type="created",
            to_status="pending_review",
            actor_user_id=actor_user_id,
            note=plan.note,
            details={"sourceType": "sales_order", "batchIndex": batch_index},
        )
    )
    return task
