from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID

from erp_api.services.logistics_order_alerts import AlertPhase, OrderAlert
from erp_api.services.logistics_order_categories import OrderCategory
from erp_api.services.logistics_order_milestones import (
    derive_milestones,
    module_tracking_status,
)
from erp_api.services.logistics_order_realtime import LogisticsOrderRealtime
from erp_api.services.logistics_shipping_methods import LogisticsShippingMethods
from erp_api.services.tiktok_order_carriers import carrier_name, names_by_package
from erp_api.services.tiktok_transport import tiktok_request_context


class LogisticsOrderStatusService:
    def __init__(self, repository, shops, client, orders) -> None:
        self._repository = repository
        self._shops = shops
        self._client = client
        self._orders = orders
        self._realtime = None
        self._shipping = None

    def configure_realtime(self, sync_service, redis):
        if self._realtime is None:
            self._realtime = LogisticsOrderRealtime(
                sync_service, self._repository._database, redis
            )
            self._repository._realtime = self._realtime
            self._shipping = LogisticsShippingMethods(self._shops, self._orders, redis)

    async def list_orders(
        self,
        tenant_id: UUID,
        *,
        page: int,
        page_size: int,
        shop_id: UUID | None,
        order_number: str | None = None,
        category: OrderCategory | None = None,
        alert: OrderAlert | None = None,
        alert_phase: AlertPhase = "overdue",
    ) -> dict[str, object]:
        result = await self._repository.list_orders(
            tenant_id,
            page=page,
            page_size=page_size,
            shop_id=shop_id,
            order_number=order_number,
            category=category,
            alert=alert,
            alert_phase=alert_phase,
        )
        if self._realtime:
            cached = await self._realtime.cached(
                tenant_id, [item["id"] for item in result["items"]]
            )
            for item in result["items"]:
                previous = cached.get(item["id"])
                if previous:
                    item["officialCheckedAt"] = previous["checkedAt"]
                    item["officialTrackingStatus"] = previous["trackingStatus"]
                    item["deliveredAt"] = previous["deliveredAt"] or item.get(
                        "deliveredAt"
                    )
                    if (
                        datetime.fromisoformat(previous["platformUpdatedAt"])
                        >= item["platformUpdatedAt"]
                    ):
                        item["packages"] = previous["packages"]
        if self._shipping:
            await self._shipping.enrich(tenant_id, result["items"])
        return result

    async def sync_page(self, tenant_id, **params):
        if self._realtime is None:
            raise RuntimeError("Realtime order sync is not configured")
        shop_results = await self._realtime.sync_shops(tenant_id, params.get("shop_id"))
        current = await self.list_orders(tenant_id, **params)
        cached = await self._realtime.cached(
            tenant_id, [item["id"] for item in current["items"]]
        )
        semaphore = asyncio.Semaphore(3)

        async def update(item):
            snapshot = cached.get(item["id"])
            if (
                snapshot
                and (
                    datetime.now(UTC) - datetime.fromisoformat(snapshot["checkedAt"])
                ).total_seconds()
                < 50
            ):
                return
            async with semaphore:
                await self.refresh(tenant_id, item["id"])

        outcomes = await asyncio.gather(
            *(update(item) for item in current["items"]), return_exceptions=True
        )
        result = await self.list_orders(tenant_id, **params)
        result["syncResults"] = shop_results
        result["refreshFailedCount"] = sum(
            isinstance(item, BaseException) for item in outcomes
        )
        return result

    async def refresh(self, tenant_id: UUID, order_id: UUID) -> dict[str, object]:
        target = await self._repository.get_target(tenant_id, order_id)
        if target is None:
            raise LookupError("Shipped TikTok order was not found.")
        shop_id = target["shop_id"]
        access_token = await self._shops.get_access_token(tenant_id, shop_id)
        shop_cipher = await self._shops.get_shop_cipher(tenant_id, shop_id)
        if not access_token or not shop_cipher:
            raise RuntimeError("TikTok shop authorization is unavailable.")
        with tiktok_request_context(tenant_id=str(tenant_id), shop_id=str(shop_id)):
            official_order = await self._orders.get_order(
                access_token,
                shop_cipher=shop_cipher,
                order_id=target["platform_order_id"],
            )
            if official_order.platform_order_id != target["platform_order_id"]:
                raise ValueError(
                    "Official order identity does not match the selected order."
                )
            events = (
                await self._client.get_tracking(
                    access_token,
                    shop_cipher=shop_cipher,
                    order_id=target["platform_order_id"],
                )
                if official_order.fulfillments
                else []
            )
            packages = []
            order_carriers = names_by_package(official_order.fulfillments)
            for package_id in dict.fromkeys(
                item.platform_package_id
                for item in official_order.fulfillments
                if item.platform_package_id
            ):
                detail = await self._client.get_package_detail(
                    access_token,
                    shop_cipher=shop_cipher,
                    package_id=package_id,
                )
                packages.append(
                    {
                        "packageId": detail.package_id,
                        "packageStatus": detail.package_status,
                        "carrierName": carrier_name(detail.carrier_name) or order_carriers.get(package_id),
                        "trackingNumberMasked": _mask(detail.tracking_number),
                    }
                )
        milestones = derive_milestones(events, target["placed_at"])
        collected = next(
            (
                event.occurred_at
                for event in events
                if module_tracking_status(event)
                in {"picked_up", "in_transit", "out_for_delivery", "delivered"}
            ),
            None,
        )
        checked_at = datetime.now(UTC)
        synced_at = await self._repository.get_synced_at(tenant_id, order_id)
        if len(packages) > 1:
            milestones["milestoneNotes"].append(
                "多包裹订单：节点按订单汇总轨迹的首次事件取值"
            )
        result = {
            "orderId": order_id,
            "trackingStatus": module_tracking_status(events[-1]) if events else None,
            "platformStatus": official_order.external_status,
            "platformUpdatedAt": official_order.platform_updated_at,
            "shippingType": official_order.shipping_type,
            "fulfillmentType": official_order.fulfillment_type,
            **milestones,
            "checkedAt": checked_at,
            "erpSyncedAt": synced_at,
            "collectedAt": collected,
            "events": [
                {
                    "status": module_tracking_status(event),
                    "actionCode": event.action_code,
                    "occurredAt": event.occurred_at,
                    "description": event.description,
                }
                for event in reversed(events)
            ],
            "packages": packages,
        }
        if self._realtime:
            await self._realtime.save(tenant_id, order_id, result)
        if self._shipping:
            await self._shipping.save(tenant_id, order_id, official_order.shipping_type,
                                      official_order.platform_updated_at, official_order.fulfillments,
                                      fulfillment_type=official_order.fulfillment_type)
        return result

    async def export_orders(
        self,
        tenant_id: UUID,
        shop_id: UUID | None,
        order_number: str | None = None,
        category: OrderCategory | None = None,
        alert: OrderAlert | None = None,
        alert_phase: AlertPhase = "overdue",
    ):
        result = await self._repository.list_orders(
            tenant_id,
            page=1,
            page_size=100_000,
            shop_id=shop_id,
            order_number=order_number,
            snapshot=True,
            category=category,
            alert=alert,
            alert_phase=alert_phase,
        )
        if self._shipping:
            await self._shipping.enrich(tenant_id, result["items"], fetch_missing=False)
        return result


def _mask(value: str | None) -> str | None:
    if not value:
        return None
    return "*" * max(0, len(value) - 4) + value[-4:]
