from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from erp_api.core.errors import register_exception_handlers
from erp_api.core.permissions import LOGISTICS_MANAGE, LOGISTICS_OPERATE, LOGISTICS_VIEW
from erp_api.routers import logistics, logistics_packing, logistics_shipping
from erp_api.routers.auth import get_authenticated_user, require_session
from erp_api.services.auth import AuthSession, CurrentUser


class FakeShippingRepository:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def list_packages(self, tenant_id: UUID, task_id: UUID):
        self.calls.append(("list_packages", {"task_id": task_id}))
        return [_package(task_id, 1), _package(task_id, 2)]

    async def list_waybills(self, tenant_id: UUID, package_id: UUID):
        return []


class FakePackingRepository:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def create_draft(self, tenant_id: UUID, task_id: UUID, **kwargs):
        self.calls.append(("create_draft", {"task_id": task_id, **kwargs}))
        return _package(task_id, 1, status="draft", version_id=1)

    async def update_draft(self, tenant_id: UUID, package_id: UUID, **kwargs):
        self.calls.append(("update_draft", {"package_id": package_id, **kwargs}))
        return _package(uuid4(), 1, status="draft", version_id=2, package_id=package_id)

    async def seal(self, tenant_id: UUID, package_id: UUID, **kwargs):
        self.calls.append(("seal", {"package_id": package_id, **kwargs}))
        return _package(
            uuid4(), 1, status="packed", version_id=3, package_id=package_id
        )

    async def unseal(self, tenant_id: UUID, package_id: UUID, **kwargs):
        self.calls.append(("unseal", {"package_id": package_id, **kwargs}))
        return _package(uuid4(), 1, status="draft", version_id=4, package_id=package_id)


class FakeCarrierRepository:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def list_carriers(self, tenant_id: UUID):
        return []

    async def create_carrier(self, tenant_id: UUID, **kwargs):
        self.calls.append(("create_carrier", kwargs))
        return _carrier()

    async def create_service(self, tenant_id: UUID, carrier_id: UUID, **kwargs):
        self.calls.append(("create_service", {"carrier_id": carrier_id, **kwargs}))
        return _service(carrier_id)

    async def create_account(self, tenant_id: UUID, carrier_id: UUID, **kwargs):
        self.calls.append(("create_account", {"carrier_id": carrier_id, **kwargs}))
        return _account(carrier_id)

    async def create_platform_mapping(
        self, tenant_id: UUID, carrier_id: UUID, **kwargs
    ):
        self.calls.append(
            ("create_platform_mapping", {"carrier_id": carrier_id, **kwargs})
        )
        return _platform_mapping(carrier_id, kwargs.get("service_id"))

    async def update_platform_mapping(
        self, tenant_id: UUID, mapping_id: UUID, **kwargs
    ):
        self.calls.append(
            ("update_platform_mapping", {"mapping_id": mapping_id, **kwargs})
        )
        return _platform_mapping(uuid4(), None, mapping_id=mapping_id, version_id=2)


def _client(permissions: list[str]):
    shipping_repository = FakeShippingRepository()
    packing_repository = FakePackingRepository()
    carrier_repository = FakeCarrierRepository()
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(logistics.router, prefix="/api")
    app.dependency_overrides[require_session] = lambda: AuthSession(
        user_id=uuid4(), tenant_id=uuid4()
    )
    app.dependency_overrides[get_authenticated_user] = lambda: CurrentUser(
        id=uuid4(), name="Admin", username="admin", roles=[], permissions=permissions
    )
    app.dependency_overrides[logistics_shipping._shipping_repository] = lambda: (
        shipping_repository
    )
    app.dependency_overrides[logistics_packing._package_repository] = lambda: (
        shipping_repository
    )
    app.dependency_overrides[logistics_packing._packing_repository] = lambda: (
        packing_repository
    )
    app.dependency_overrides[logistics_shipping._carrier_repository] = lambda: (
        carrier_repository
    )
    return TestClient(app), shipping_repository, packing_repository, carrier_repository


def test_package_panel_creates_updates_seals_and_unseals() -> None:
    task_id = uuid4()
    update_payload = {
        "versionId": 1,
        "items": [{"taskItemId": str(uuid4()), "quantity": 1}],
        "weightGrams": 500,
        "lengthMm": 200,
        "widthMm": 150,
        "heightMm": 100,
    }
    client, _, packing, _ = _client([LOGISTICS_VIEW, LOGISTICS_OPERATE])
    with client:
        draft = client.post(f"/api/logistics/tasks/{task_id}/packages", json={})
        package_id = draft.json()["id"]
        updated = client.patch(
            f"/api/logistics/packages/{package_id}", json=update_payload
        )
        sealed = client.post(
            f"/api/logistics/packages/{package_id}/seal", json={"versionId": 2}
        )
        unsealed = client.post(
            f"/api/logistics/packages/{package_id}/unseal", json={"versionId": 3}
        )
        listing = client.get(f"/api/logistics/tasks/{task_id}/packages")

    assert draft.status_code == 201
    assert updated.status_code == 200
    assert sealed.json()["status"] == "packed"
    assert unsealed.json()["status"] == "draft"
    assert listing.status_code == 200
    assert len(listing.json()) == 2
    assert [call[0] for call in packing.calls] == [
        "create_draft",
        "update_draft",
        "seal",
        "unseal",
    ]


def test_package_creation_requires_operate_permission() -> None:
    client, repository, packing, _ = _client([LOGISTICS_VIEW])
    with client:
        response = client.post(
            f"/api/logistics/tasks/{uuid4()}/packages",
            json={},
        )

    assert response.status_code == 403
    assert repository.calls == []
    assert packing.calls == []


def test_carrier_account_requires_manage_and_never_returns_secret_reference() -> None:
    carrier_id = uuid4()
    payload = {
        "accountName": "Production",
        "accountIdentifierMasked": "****7788",
        "authType": "api_key",
        "secretReference": "vault://erp/logistics/carrier-a",
    }
    forbidden_client, _, _, _ = _client([LOGISTICS_VIEW])
    with forbidden_client:
        forbidden = forbidden_client.post(
            f"/api/logistics/carriers/{carrier_id}/accounts", json=payload
        )
    client, _, _, repository = _client([LOGISTICS_VIEW, LOGISTICS_MANAGE])
    with client:
        created = client.post(
            f"/api/logistics/carriers/{carrier_id}/accounts", json=payload
        )

    assert forbidden.status_code == 403
    assert created.status_code == 201
    assert created.json()["hasSecret"] is True
    assert "secretReference" not in created.json()
    assert repository.calls[0][1]["secret_reference"] == payload["secretReference"]


def test_carrier_service_accepts_platform_provider_ids() -> None:
    carrier_id = uuid4()
    client, _, _, repository = _client([LOGISTICS_VIEW, LOGISTICS_MANAGE])
    with client:
        response = client.post(
            f"/api/logistics/carriers/{carrier_id}/services",
            json={
                "code": "STANDARD",
                "name": "Standard",
                "platformProviderIds": {"TikTok": "provider-123"},
                "trackingStatusMap": {"CUSTOM_TRANSIT": "in_transit"},
            },
        )

    assert response.status_code == 201
    assert repository.calls[0][1]["platform_provider_ids"] == {"tiktok": "provider-123"}
    assert repository.calls[0][1]["tracking_status_map"] == {
        "CUSTOM_TRANSIT": "in_transit"
    }


def test_platform_carrier_mapping_normalizes_scope_and_requires_manage() -> None:
    carrier_id = uuid4()
    service_id = uuid4()
    store_id = uuid4()
    payload = {
        "storeId": str(store_id),
        "platform": " TikTok ",
        "region": "us",
        "serviceId": str(service_id),
        "platformCarrierId": " 123456789 ",
        "platformCarrierCode": " UPS ",
        "platformCarrierName": "TikTok Logistics",
        "deliveryOptionId": " delivery-option-1 ",
        "rawPayload": {"id": "123456789", "name": "UPS"},
    }
    forbidden_client, _, _, _ = _client([LOGISTICS_VIEW])
    with forbidden_client:
        forbidden = forbidden_client.post(
            f"/api/logistics/carriers/{carrier_id}/platform-mappings", json=payload
        )
    client, _, _, repository = _client([LOGISTICS_VIEW, LOGISTICS_MANAGE])
    with client:
        created = client.post(
            f"/api/logistics/carriers/{carrier_id}/platform-mappings", json=payload
        )

    assert forbidden.status_code == 403
    assert created.status_code == 201
    assert repository.calls[0][1] == {
        "carrier_id": carrier_id,
        "store_id": store_id,
        "platform": "tiktok",
        "region": "US",
        "service_id": service_id,
        "platform_carrier_id": "123456789",
        "platform_carrier_code": "UPS",
        "platform_carrier_name": "TikTok Logistics",
        "delivery_option_id": "delivery-option-1",
        "raw_payload": {"id": "123456789", "name": "UPS"},
    }


def test_platform_carrier_mapping_update_uses_optimistic_version() -> None:
    mapping_id = uuid4()
    client, _, _, repository = _client([LOGISTICS_VIEW, LOGISTICS_MANAGE])
    with client:
        response = client.patch(
            f"/api/logistics/platform-carrier-mappings/{mapping_id}",
            json={"versionId": 1, "status": "inactive"},
        )

    assert response.status_code == 200
    assert repository.calls[0][1] == {
        "mapping_id": mapping_id,
        "version_id": 1,
        "status": "inactive",
        "platform_carrier_id": None,
        "platform_carrier_code": None,
        "platform_carrier_name": None,
        "delivery_option_id": None,
        "raw_payload": None,
    }


def _package(
    task_id: UUID,
    ordinal: int,
    *,
    status: str = "packed",
    version_id: int = 1,
    package_id: UUID | None = None,
) -> dict[str, object]:
    now = datetime(2026, 8, 24, tzinfo=UTC)
    return {
        "id": package_id or uuid4(),
        "taskId": task_id,
        "packageNumber": f"LP-20260824-{ordinal:04d}",
        "status": status,
        "weightGrams": None,
        "lengthMm": None,
        "widthMm": None,
        "heightMm": None,
        "note": None,
        "createdByUserId": uuid4(),
        "sealedByUserId": uuid4() if status == "packed" else None,
        "sealedAt": now if status == "packed" else None,
        "createdAt": now,
        "updatedAt": now,
        "versionId": version_id,
        "items": [],
    }


def _carrier() -> dict[str, object]:
    now = datetime(2026, 8, 24, tzinfo=UTC)
    return {
        "id": uuid4(),
        "code": "CARRIER_A",
        "name": "Carrier A",
        "adapterKey": "manual",
        "status": "active",
        "trackingUrlTemplate": None,
        "createdAt": now,
        "updatedAt": now,
        "versionId": 1,
        "services": [],
        "accounts": [],
    }


def _service(carrier_id: UUID) -> dict[str, object]:
    return {
        "id": uuid4(),
        "carrierId": carrier_id,
        "code": "STANDARD",
        "name": "Standard",
        "serviceLevel": "standard",
        "supportedCountries": ["US"],
        "platformProviderIds": {"tiktok": "provider-123"},
        "trackingStatusMap": {},
        "status": "active",
        "versionId": 1,
    }


def _account(carrier_id: UUID) -> dict[str, object]:
    now = datetime(2026, 8, 24, tzinfo=UTC)
    return {
        "id": uuid4(),
        "carrierId": carrier_id,
        "accountName": "Production",
        "accountIdentifierMasked": "****7788",
        "authType": "api_key",
        "status": "active",
        "hasSecret": True,
        "createdAt": now,
        "updatedAt": now,
        "versionId": 1,
    }


def _platform_mapping(
    carrier_id: UUID,
    service_id: UUID | None,
    *,
    mapping_id: UUID | None = None,
    version_id: int = 1,
) -> dict[str, object]:
    now = datetime(2026, 8, 25, tzinfo=UTC)
    return {
        "id": mapping_id or uuid4(),
        "carrierId": carrier_id,
        "serviceId": service_id,
        "storeId": uuid4(),
        "platform": "tiktok",
        "region": "US",
        "platformCarrierId": "123456789",
        "platformCarrierCode": "UPS",
        "platformCarrierName": "TikTok Logistics",
        "deliveryOptionId": "delivery-option-1",
        "rawPayload": {"id": "123456789", "name": "UPS"},
        "status": "active",
        "createdAt": now,
        "updatedAt": now,
        "versionId": version_id,
    }
