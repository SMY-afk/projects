from __future__ import annotations

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
from erp_api.models.shop import Shop
from erp_api.services.logistics_records import task_record


class LogisticsSourceNotFoundError(ValueError):
    pass


class LogisticsTaskValidationError(ValueError):
    pass


class LogisticsTaskConflictError(ValueError):
    pass


@dataclass(frozen=True)
class LogisticsTaskItemInput:
    source_line_id: UUID
    planned_quantity: int


@dataclass(frozen=True)
class LogisticsTaskPage:
    items: list[dict[str, object]]
    total: int


class LogisticsRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def list_shop_options(self, tenant_id: UUID) -> list[dict[str, object]]:
        async for session in self._database.session(tenant_id):
            shops = await session.scalars(
                select(Shop).order_by(Shop.shop_name, Shop.id)
            )
            return [
                {
                    "id": shop.id,
                    "shopName": shop.shop_name,
                    "platform": shop.platform,
                    "platformShopId": shop.platform_shop_id,
                }
                for shop in shops.all()
            ]
        return []

    async def list_tasks(
        self,
        tenant_id: UUID,
        *,
        page: int,
        page_size: int,
        status: str | None = None,
        source_type: str | None = None,
        shop_id: UUID | None = None,
        priority: str | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
    ) -> LogisticsTaskPage:
        filters = []
        if status:
            filters.append(LogisticsTask.status == status)
        if source_type:
            filters.append(LogisticsTask.source_type == source_type)
        if shop_id:
            filters.append(LogisticsTask.shop_id == shop_id)
        if priority:
            filters.append(LogisticsTask.priority == priority)
        if created_from:
            filters.append(LogisticsTask.created_at >= created_from)
        if created_to:
            filters.append(LogisticsTask.created_at < created_to)
        async for session in self._database.session(tenant_id):
            tasks = await session.scalars(
                _task_select()
                .where(*filters)
                .order_by(LogisticsTask.created_at.desc(), LogisticsTask.id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            total = await session.scalar(
                select(func.count()).select_from(LogisticsTask).where(*filters)
            )
            return LogisticsTaskPage(
                items=[task_record(task) for task in tasks.unique().all()],
                total=total or 0,
            )
        raise RuntimeError("Tenant database session was not created.")

    async def get_task(
        self, tenant_id: UUID, task_id: UUID
    ) -> dict[str, object] | None:
        async for session in self._database.session(tenant_id):
            task = await _load_task(session, task_id)
            return task_record(task) if task else None
        return None

    async def get_order_context(
        self, tenant_id: UUID, task_id: UUID
    ) -> dict[str, object] | None:
        async for session in self._database.session(tenant_id):
            order_id = await session.scalar(
                select(LogisticsTask.order_id).where(LogisticsTask.id == task_id)
            )
            if order_id is None:
                return None
            order = await session.scalar(
                select(Order)
                .options(selectinload(Order.shop), selectinload(Order.recipient))
                .where(Order.id == order_id)
            )
            if order is None:
                return None
            recipient = order.recipient
            return {
                "orderId": order.id,
                "orderNumber": order.order_number,
                "shopId": order.shop_id,
                "shopName": order.shop.shop_name if order.shop else "",
                "status": order.status,
                "externalStatus": order.external_status,
                "buyerUsernameMasked": order.buyer_username_masked,
                "placedAt": order.placed_at,
                "maskedRecipient": (
                    {
                        "name": recipient.name_masked,
                        "phone": recipient.phone_masked,
                        "address": recipient.address_masked,
                        "countryCode": recipient.country_code,
                        "purged": recipient.purged_at is not None,
                    }
                    if recipient
                    else None
                ),
            }
        return None

    async def create_sales_order_task(
        self,
        tenant_id: UUID,
        *,
        actor_user_id: UUID,
        order_id: UUID,
        items: list[LogisticsTaskItemInput],
        priority: str,
        note: str | None,
    ) -> dict[str, object]:
        if len({item.source_line_id for item in items}) != len(items):
            raise LogisticsTaskValidationError("A source line can appear only once.")
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
            existing_planned = await _planned_quantities(
                session, order_id, [item.source_line_id for item in items]
            )
            task = LogisticsTask(
                tenant_id=tenant_id,
                task_number=_task_number(),
                source_type="sales_order",
                source_reference_id=order.id,
                source_number=order.order_number,
                order_id=order.id,
                shop_id=order.shop_id,
                priority=priority,
                status="pending_review",
                note=note,
                created_by_user_id=actor_user_id,
            )
            for item in items:
                line = order_lines.get(item.source_line_id)
                if line is None:
                    raise LogisticsTaskValidationError(
                        "A selected source line does not belong to the sales order."
                    )
                available = line.quantity - existing_planned.get(line.id, 0)
                if item.planned_quantity > available:
                    raise LogisticsTaskConflictError(
                        "Selected quantity exceeds the unassigned order quantity."
                    )
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
                    note=note,
                    details={"sourceType": "sales_order"},
                )
            )
            session.add(task)
            await session.commit()
            stored = await _load_task(session, task.id)
            if stored is None:
                raise RuntimeError("Created logistics task could not be reloaded.")
            return task_record(stored)
        raise RuntimeError("Tenant database session was not created.")


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
            LogisticsTaskItem.order_line_id.in_(line_ids),
        )
        .group_by(LogisticsTaskItem.order_line_id)
    )
    return {line_id: int(quantity) for line_id, quantity in rows}


def _task_select():
    return select(LogisticsTask).options(
        selectinload(LogisticsTask.items),
        selectinload(LogisticsTask.operations),
        selectinload(LogisticsTask.reviews),
    )


async def _load_task(session, task_id: UUID) -> LogisticsTask | None:
    return await session.scalar(
        _task_select()
        .where(LogisticsTask.id == task_id)
        .execution_options(populate_existing=True)
    )


def _task_number() -> str:
    return f"LT-{datetime.now(UTC):%Y%m%d}-{uuid4().hex[:10].upper()}"
