from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import and_, exists, or_, select
from sqlalchemy.orm import selectinload

from erp_api.infrastructure.database import Database
from erp_api.models.logistics_package import LogisticsPackage
from erp_api.models.logistics_task import LogisticsTask
from erp_api.models.logistics_task_operation import LogisticsTaskOperation
from erp_api.models.logistics_waybill import LogisticsWaybill
from erp_api.models.order import Order
from erp_api.models.order_fulfillment import OrderFulfillment
from erp_api.models.shop import Shop
from erp_api.models.user import User
from erp_api.services.tiktok_platform_logistics_sync_carriers import (
    resolve_platform_carrier,
)
from erp_api.services.tiktok_platform_logistics_sync_persistence import (
    advance_task_items,
    assign_package_items,
    create_package,
    create_task,
    ensure_task_items,
    update_order_fulfillment,
    update_package_and_waybill,
)
from erp_api.services.tiktok_platform_logistics_sync_records import (
    merge_task_status,
    waybill_number,
)
from erp_api.services.tiktok_platform_logistics_sync_service import (
    PersistedPlatformWaybill,
    PlatformOrderTarget,
)
from erp_api.services.token_cipher import TokenCipher

ACTIVE_PLATFORM_STATUSES = {"AWAITING_COLLECTION", "IN_TRANSIT"}
TERMINAL_TASK_STATUSES = {"delivered", "cancelled"}


class PlatformLogisticsSyncRepository:
    def __init__(self, database: Database, tracking_cipher: TokenCipher) -> None:
        self._database = database
        self._tracking_cipher = tracking_cipher

    async def list_tenant_ids(self) -> list[UUID]:
        async with self._database.system_session_factory() as session:
            values = await session.scalars(
                select(Shop.tenant_id)
                .where(Shop.platform == "tiktok", Shop.status == "active")
                .distinct()
            )
            return list(values.all())

    async def list_tiktok_shops(
        self, tenant_id: UUID, shop_id: UUID | None = None
    ) -> list[UUID]:
        async for session in self._database.session(tenant_id):
            query = select(Shop.id).where(
                Shop.platform == "tiktok", Shop.status == "active"
            )
            if shop_id is not None:
                query = query.where(Shop.id == shop_id)
            return list((await session.scalars(query.order_by(Shop.id))).all())
        return []

    async def list_targets(
        self, tenant_id: UUID, shop_id: UUID
    ) -> list[PlatformOrderTarget]:
        open_task = exists(
            select(LogisticsTask.id).where(
                LogisticsTask.order_id == Order.id,
                LogisticsTask.status.not_in(TERMINAL_TASK_STATUSES),
            )
        )
        async for session in self._database.session(tenant_id):
            rows = await session.execute(
                select(
                    Order.id,
                    Order.platform_order_id,
                    OrderFulfillment.platform_package_id,
                )
                .join(OrderFulfillment, OrderFulfillment.order_id == Order.id)
                .where(
                    Order.shop_id == shop_id,
                    OrderFulfillment.platform_package_id != "",
                    or_(
                        Order.external_status.in_(ACTIVE_PLATFORM_STATUSES),
                        and_(
                            open_task,
                            Order.external_status.in_(
                                {"DELIVERED", "COMPLETED", "CANCELLED"}
                            ),
                        ),
                    ),
                )
                .order_by(Order.platform_updated_at, Order.id)
            )
            grouped: dict[UUID, tuple[str, list[str]]] = {}
            for order_id, platform_order_id, package_id in rows:
                current = grouped.setdefault(order_id, (platform_order_id, []))
                if package_id not in current[1]:
                    current[1].append(package_id)
            return [
                PlatformOrderTarget(
                    order_id, shop_id, platform_order_id, tuple(packages)
                )
                for order_id, (platform_order_id, packages) in grouped.items()
            ]
        return []

    async def persist_order(
        self,
        tenant_id: UUID,
        target: PlatformOrderTarget,
        package_details: list,
        *,
        actor_user_id: UUID | None = None,
    ) -> list[PersistedPlatformWaybill]:
        async for session in self._database.session(tenant_id):
            order = await session.scalar(
                select(Order)
                .options(
                    selectinload(Order.lines),
                    selectinload(Order.fulfillments),
                )
                .where(Order.id == target.order_id)
                .with_for_update()
            )
            if order is None:
                raise ValueError("Platform logistics order was not found.")
            actor_id = actor_user_id or await session.scalar(
                select(User.id).where(User.status == "active").order_by(User.created_at)
            )
            if actor_id is None:
                raise ValueError("Platform logistics sync requires an active user.")
            task, created = await self._load_or_create_task(
                session,
                tenant_id,
                order,
                actor_id,
                set(target.platform_package_ids),
            )
            previous_status = task.status
            task.status = merge_task_status(task.status, order.external_status)
            task.updated_at = datetime.now(UTC)
            advance_task_items(task, order)
            persisted = []
            for detail in package_details:
                carrier = await self._resolve_carrier(
                    session, tenant_id, order.shop_id, detail
                )
                waybill = await session.scalar(
                    select(LogisticsWaybill).where(
                        LogisticsWaybill.external_waybill_id == detail.package_id
                    )
                )
                if waybill is None:
                    package = create_package(tenant_id, task, detail, actor_id)
                    session.add(package)
                    await session.flush()
                    assign_package_items(tenant_id, package, task, order, detail)
                    waybill = LogisticsWaybill(
                        tenant_id=tenant_id,
                        package_id=package.id,
                        carrier_id=carrier.id,
                        waybill_number=waybill_number(),
                        external_waybill_id=detail.package_id,
                        is_current=True,
                    )
                    session.add(waybill)
                else:
                    package = await session.get(
                        LogisticsPackage, waybill.package_id, with_for_update=True
                    )
                    if package is None:
                        raise ValueError("Platform logistics package was not found.")
                update_package_and_waybill(
                    package,
                    waybill,
                    carrier.id,
                    order.external_status,
                    detail,
                    self._tracking_cipher,
                )
                update_order_fulfillment(order, detail, self._tracking_cipher)
                persisted.append(
                    PersistedPlatformWaybill(
                        carrier.id, detail.package_id, detail.tracking_number
                    )
                )
            if created or previous_status != task.status:
                task.operations.append(
                    LogisticsTaskOperation(
                        tenant_id=tenant_id,
                        operation_type="platform_logistics_synced",
                        from_status=None if created else previous_status,
                        to_status=task.status,
                        actor_user_id=actor_id,
                        details={
                            "platform": "tiktok",
                            "packageCount": len(package_details),
                        },
                    )
                )
            await session.commit()
            return persisted
        raise RuntimeError("Tenant database session was not created.")

    async def _load_or_create_task(
        self, session, tenant_id, order, actor_id, platform_package_ids
    ):
        tasks = await session.scalars(
            select(LogisticsTask)
            .options(
                selectinload(LogisticsTask.items),
                selectinload(LogisticsTask.packages).selectinload(
                    LogisticsPackage.waybills
                ),
                selectinload(LogisticsTask.operations),
            )
            .where(
                LogisticsTask.order_id == order.id,
                LogisticsTask.source_type == "sales_order",
                LogisticsTask.status != "cancelled",
            )
            .order_by(LogisticsTask.created_at)
        )
        task_items = tasks.unique().all()
        task = next(
            (
                item
                for item in task_items
                if any(
                    waybill.external_waybill_id in platform_package_ids
                    for package in item.packages
                    for waybill in package.waybills
                )
            ),
            None,
        )
        task = task or next((item for item in task_items if not item.packages), None)
        if task is not None:
            ensure_task_items(tenant_id, task, order)
            return task, False
        task = create_task(tenant_id, order, actor_id)
        session.add(task)
        await session.flush()
        return task, True

    async def _resolve_carrier(self, session, tenant_id, shop_id, detail):
        return await resolve_platform_carrier(session, tenant_id, shop_id, detail)
