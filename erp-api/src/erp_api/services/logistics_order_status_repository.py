from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select

from erp_api.infrastructure.database import Database
from erp_api.models.logistics_package import LogisticsPackage
from erp_api.models.logistics_task import LogisticsTask
from erp_api.models.logistics_tracking_event import LogisticsTrackingEvent
from erp_api.models.logistics_waybill import LogisticsWaybill
from erp_api.models.order import Order
from erp_api.models.order_fulfillment import OrderFulfillment
from erp_api.models.shop import Shop
from erp_api.services.logistics_alert_settings import LogisticsAlertSettings
from erp_api.services.logistics_order_alerts import (
    AlertPhase,
    OrderAlert,
    matches_phase,
    warning_snapshot,
)
from erp_api.services.logistics_order_categories import (
    MODULE_STATUSES,
    OrderCategory,
    category_condition,
    category_counts,
    delivered_since,
)
from erp_api.services.logistics_order_delivery_times import delivered_times
from erp_api.services.tiktok_tracking_event_status import tracking_status


class LogisticsOrderStatusRepository:
    def __init__(self, database: Database) -> None:
        self._database = database
        self._realtime = None
        self._alert_settings = LogisticsAlertSettings()

    async def list_orders(
        self,
        tenant_id: UUID,
        *,
        page: int,
        page_size: int,
        shop_id: UUID | None = None,
        order_number: str | None = None,
        snapshot: bool = False,
        category: OrderCategory | None = None,
        alert: OrderAlert | None = None,
        alert_phase: AlertPhase = "overdue",
    ) -> dict[str, object]:
        async for session in self._database.session(tenant_id):
            await session.connection(
                execution_options={"isolation_level": "REPEATABLE READ"}
            )
            conditions = [
                Order.tenant_id == tenant_id,
                Shop.platform == "tiktok",
                Shop.tenant_id == tenant_id,
            ]
            if shop_id is not None:
                conditions.append(Order.shop_id == shop_id)
            if order_number and order_number.strip():
                conditions.append(Order.order_number == order_number.strip())
            matches, warnings = await warning_snapshot(
                session, tenant_id, shop_id, order_number, self._realtime,
                lead_hours=self._alert_settings.read(tenant_id).leadHours,
            )
            since = delivered_since()
            grouped = (
                await session.execute(
                    select(Order.external_status, func.count())
                    .join(Shop, Shop.id == Order.shop_id)
                    .where(*conditions, category_condition(None, since))
                    .group_by(Order.external_status)
                )
            ).all()
            counts = category_counts(dict(grouped))
            if alert:
                conditions.append(
                    Order.id.in_(
                        [key for key, flags in matches.items() if matches_phase(flags, alert, alert_phase)]
                    )
                )
            else:
                conditions.append(category_condition(category, since))
            base = (
                select(Order.id).join(Shop, Shop.id == Order.shop_id).where(*conditions)
            )
            total = await session.scalar(
                select(func.count()).select_from(base.subquery())
            )
            if snapshot and (total or 0) > page_size:
                raise ValueError("Too many orders; select one shop before exporting.")
            ordering = (
                [Order.placed_at.asc(), Order.id.asc()]
                if alert
                else [Order.platform_updated_at.desc(), Order.id.desc()]
            )
            rows = (
                await session.execute(
                    select(Order, Shop.shop_name)
                    .join(Shop, Shop.id == Order.shop_id)
                    .where(*conditions)
                    .order_by(*ordering)
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
            order_ids = [order.id for order, _ in rows]
            delivered = await delivered_times(session, tenant_id, order_ids)
            fulfillments: dict[UUID, list[dict[str, object]]] = {
                order_id: [] for order_id in order_ids
            }
            for offset in range(0, len(order_ids), 1000):
                batch = order_ids[offset : offset + 1000]
                tracking = await self._tracking_for_orders(session, tenant_id, batch)
                package_rows = await session.scalars(
                    select(OrderFulfillment)
                    .where(
                        OrderFulfillment.order_id.in_(batch),
                        OrderFulfillment.tenant_id == tenant_id,
                    )
                    .order_by(OrderFulfillment.platform_package_id)
                )
                for package in package_rows:
                    last_event = tracking.get(
                        (package.order_id, package.platform_package_id)
                    )
                    fulfillments[package.order_id].append(
                        {
                            "packageId": package.platform_package_id,
                            "packageStatus": package.status,
                            "carrierName": package.carrier,
                            "trackingNumberMasked": package.tracking_number_masked,
                            "trackingStatus": (
                                tracking_status(
                                    (last_event.external_event_id or "").split(":")[2],
                                    last_event.description,
                                )
                                if last_event
                                else None
                            ),
                            "trackingCheckedAt": (
                                last_event.received_at if last_event else None
                            ),
                        }
                    )
            return {
                "items": [
                    {
                        "id": order.id,
                        "shopId": order.shop_id,
                        "shopName": shop_name,
                        "orderNumber": order.order_number,
                        "platformOrderId": order.platform_order_id,
                        "orderCreatedAt": order.placed_at,
                        "platformStatus": order.external_status,
                        "platformUpdatedAt": order.platform_updated_at,
                        "erpSyncedAt": order.synced_at,
                        "deliveredAt": delivered.get(order.id),
                        "packages": fulfillments[order.id],
                        "alerts": matches.get(order.id, {}),
                    }
                    for order, shop_name in rows
                ],
                "total": total or 0,
                "page": page,
                "pageSize": page_size,
                "categoryCounts": counts,
                "warnings": warnings,
            }
        raise RuntimeError("Tenant database session was not created.")

    async def _tracking_for_orders(self, session, tenant_id, order_ids):
        if not order_ids:
            return {}
        waybills = (
            await session.execute(
                select(
                    LogisticsTask.order_id,
                    LogisticsWaybill.external_waybill_id,
                    LogisticsWaybill.id,
                )
                .join(LogisticsPackage, LogisticsPackage.task_id == LogisticsTask.id)
                .join(
                    LogisticsWaybill, LogisticsWaybill.package_id == LogisticsPackage.id
                )
                .where(
                    LogisticsTask.order_id.in_(order_ids),
                    LogisticsTask.tenant_id == tenant_id,
                    LogisticsPackage.tenant_id == tenant_id,
                    LogisticsWaybill.tenant_id == tenant_id,
                    LogisticsWaybill.is_current.is_(True),
                )
            )
        ).all()
        if not waybills:
            return {}
        events = await session.scalars(
            select(LogisticsTrackingEvent)
            .where(
                LogisticsTrackingEvent.waybill_id.in_(
                    [waybill_id for _, _, waybill_id in waybills]
                ),
                LogisticsTrackingEvent.tenant_id == tenant_id,
                LogisticsTrackingEvent.accepted.is_(True),
                LogisticsTrackingEvent.external_event_id.like("tiktok:%"),
            )
            .order_by(
                LogisticsTrackingEvent.occurred_at.desc(),
                LogisticsTrackingEvent.received_at.desc(),
            )
        )
        latest_by_waybill = {}
        for event in events:
            latest_by_waybill.setdefault(event.waybill_id, event)
        return {
            (order_id, package_id): latest_by_waybill[waybill_id]
            for order_id, package_id, waybill_id in waybills
            if package_id and waybill_id in latest_by_waybill
        }

    async def get_synced_at(self, tenant_id: UUID, order_id: UUID):
        async for session in self._database.session(tenant_id):
            return await session.scalar(
                select(Order.synced_at).where(
                    Order.id == order_id, Order.tenant_id == tenant_id
                )
            )
        raise RuntimeError("Tenant database session was not created.")

    async def get_target(self, tenant_id: UUID, order_id: UUID):
        async for session in self._database.session(tenant_id):
            order = await session.scalar(
                select(Order)
                .join(Shop, Shop.id == Order.shop_id)
                .where(
                    Order.id == order_id,
                    Order.tenant_id == tenant_id,
                    Order.external_status.in_(MODULE_STATUSES),
                    Shop.platform == "tiktok",
                    Shop.tenant_id == tenant_id,
                )
            )
            if order is None:
                return None
            packages = await session.scalars(
                select(OrderFulfillment.platform_package_id)
                .where(
                    OrderFulfillment.order_id == order_id,
                    OrderFulfillment.tenant_id == tenant_id,
                )
                .order_by(OrderFulfillment.platform_package_id)
            )
            return {
                "shop_id": order.shop_id,
                "platform_order_id": order.platform_order_id,
                "placed_at": order.placed_at,
                "platform_package_ids": tuple(value for value in packages if value),
            }
        return None
