from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from uuid import UUID

from erp_api.services.tiktok_transport import tiktok_request_context

logger = logging.getLogger("erp_api.tiktok_logistics_sync")


@dataclass(frozen=True)
class PlatformOrderTarget:
    order_id: UUID
    shop_id: UUID
    platform_order_id: str
    platform_package_ids: tuple[str, ...]


@dataclass(frozen=True)
class PersistedPlatformWaybill:
    carrier_id: UUID
    external_waybill_id: str
    tracking_number: str | None


class PlatformLogisticsSyncService:
    def __init__(
        self,
        repository,
        shop_repository,
        client,
        tracking_repository,
        exception_service,
        *,
        package_concurrency: int = 4,
    ) -> None:
        self._repository = repository
        self._shops = shop_repository
        self._client = client
        self._tracking = tracking_repository
        self._exceptions = exception_service
        self._package_concurrency = package_concurrency

    async def sync_tenant(
        self,
        tenant_id: UUID,
        *,
        shop_id: UUID | None = None,
        actor_user_id: UUID | None = None,
    ) -> dict[str, int]:
        result = _empty_result()
        shop_ids = await self._repository.list_tiktok_shops(tenant_id, shop_id)
        result["shopsScanned"] = len(shop_ids)
        for current_shop_id in shop_ids:
            await self._sync_shop(
                tenant_id,
                current_shop_id,
                actor_user_id=actor_user_id,
                result=result,
            )
        detected = await self._exceptions.scan_tenant(tenant_id)
        result["exceptionsScanned"] = detected["scanned"]
        result["exceptionsDetected"] = detected["detected"]
        return result

    async def sync_all(self) -> dict[str, int]:
        total = _empty_result()
        for tenant_id in await self._repository.list_tenant_ids():
            current = await self.sync_tenant(tenant_id)
            for key, value in current.items():
                total[key] += value
        return total

    async def _sync_shop(
        self,
        tenant_id: UUID,
        shop_id: UUID,
        *,
        actor_user_id: UUID | None,
        result: dict[str, int],
    ) -> None:
        access_token, shop_cipher = await asyncio.gather(
            self._shops.get_access_token(tenant_id, shop_id),
            self._shops.get_shop_cipher(tenant_id, shop_id),
        )
        targets = await self._repository.list_targets(tenant_id, shop_id)
        result["ordersScanned"] += len(targets)
        if not access_token or not shop_cipher:
            result["failedOrders"] += len(targets)
            return
        for target in targets:
            try:
                await self._sync_order(
                    tenant_id,
                    target,
                    access_token=access_token,
                    shop_cipher=shop_cipher,
                    actor_user_id=actor_user_id,
                    result=result,
                )
            except Exception as error:  # noqa: BLE001 - isolate one platform order
                result["failedOrders"] += 1
                logger.warning(
                    "tiktok_logistics_order_sync_failed",
                    extra={
                        "event": "tiktok_logistics_order_sync_failed",
                        "tenant_id": str(tenant_id),
                        "shop_id": str(shop_id),
                        "error_code": type(error).__name__[:64],
                    },
                )

    async def _sync_order(
        self,
        tenant_id: UUID,
        target: PlatformOrderTarget,
        *,
        access_token: str,
        shop_cipher: str,
        actor_user_id: UUID | None,
        result: dict[str, int],
    ) -> None:
        semaphore = asyncio.Semaphore(self._package_concurrency)

        async def package_detail(package_id: str):
            async with semaphore:
                return await self._client.get_package_detail(
                    access_token,
                    shop_cipher=shop_cipher,
                    package_id=package_id,
                )

        with tiktok_request_context(
            tenant_id=str(tenant_id), shop_id=str(target.shop_id)
        ):
            package_details, events = await asyncio.gather(
                asyncio.gather(
                    *(package_detail(value) for value in target.platform_package_ids)
                ),
                self._client.get_tracking(
                    access_token,
                    shop_cipher=shop_cipher,
                    order_id=target.platform_order_id,
                ),
            )
        waybills = await self._repository.persist_order(
            tenant_id,
            target,
            list(package_details),
            actor_user_id=actor_user_id,
        )
        result["packagesSynced"] += len(package_details)
        for waybill in waybills:
            for event in events:
                applied = await self._tracking.apply_update(
                    tenant_id,
                    waybill.carrier_id,
                    event.as_update(
                        external_waybill_id=waybill.external_waybill_id,
                        tracking_number=waybill.tracking_number,
                    ),
                    source="poll",
                    payload_hash=event.payload_hash,
                )
                result["trackingEventsSynced"] += int(
                    not getattr(applied, "duplicate", False)
                )


def _empty_result() -> dict[str, int]:
    return {
        "shopsScanned": 0,
        "ordersScanned": 0,
        "packagesSynced": 0,
        "trackingEventsSynced": 0,
        "failedOrders": 0,
        "exceptionsScanned": 0,
        "exceptionsDetected": 0,
    }
