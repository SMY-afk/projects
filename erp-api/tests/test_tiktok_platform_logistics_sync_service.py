from types import SimpleNamespace
from uuid import uuid4

import pytest

from erp_api.services.tiktok_platform_logistics_sync_service import (
    PlatformLogisticsSyncService,
    PlatformOrderTarget,
)


class FakeRepository:
    def __init__(self) -> None:
        self.persisted = []

    async def list_tiktok_shops(self, tenant_id, shop_id=None):
        return [uuid4()]

    async def list_targets(self, tenant_id, shop_id):
        return [PlatformOrderTarget(uuid4(), shop_id, "order-1", ("pkg-1",))]

    async def persist_order(
        self, tenant_id, target, package_details, actor_user_id=None
    ):
        self.persisted.append((tenant_id, target, package_details, actor_user_id))
        return [
            SimpleNamespace(
                carrier_id=uuid4(),
                external_waybill_id="pkg-1",
                tracking_number="TRACK-1",
            )
        ]


class FakeShopRepository:
    async def get_access_token(self, tenant_id, shop_id):
        return "token"

    async def get_shop_cipher(self, tenant_id, shop_id):
        return "cipher"


class FakeClient:
    async def get_package_detail(self, access_token, *, shop_cipher, package_id):
        return SimpleNamespace(package_id=package_id, tracking_number="TRACK-1")

    async def get_tracking(self, access_token, *, shop_cipher, order_id):
        return [
            SimpleNamespace(
                as_update=lambda **kwargs: SimpleNamespace(**kwargs),
                payload_hash="hash",
            )
        ]


class FakeTrackingRepository:
    def __init__(self) -> None:
        self.updates = []

    async def apply_update(
        self, tenant_id, carrier_id, update, *, source, payload_hash
    ):
        self.updates.append((tenant_id, carrier_id, update, source, payload_hash))


class FakeExceptionService:
    async def scan_tenant(self, tenant_id):
        return {"scanned": 1, "detected": 1}


@pytest.mark.asyncio
async def test_sync_persists_real_package_then_tracking_and_detects_exceptions() -> (
    None
):
    repository = FakeRepository()
    tracking_repository = FakeTrackingRepository()
    service = PlatformLogisticsSyncService(
        repository,
        FakeShopRepository(),
        FakeClient(),
        tracking_repository,
        FakeExceptionService(),
    )
    tenant_id = uuid4()

    result = await service.sync_tenant(tenant_id)

    assert result == {
        "shopsScanned": 1,
        "ordersScanned": 1,
        "packagesSynced": 1,
        "trackingEventsSynced": 1,
        "failedOrders": 0,
        "exceptionsScanned": 1,
        "exceptionsDetected": 1,
    }
    assert len(repository.persisted) == 1
    assert tracking_repository.updates[0][3:] == ("poll", "hash")
