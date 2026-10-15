from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from erp_api.core.errors import register_exception_handlers
from erp_api.core.permissions import LOGISTICS_DISPATCH, LOGISTICS_VIEW
from erp_api.routers import logistics, logistics_shipping
from erp_api.routers.auth import get_authenticated_user, require_session
from erp_api.services.auth import AuthSession, CurrentUser


class FakeShippingService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def quote(self, tenant_id: UUID, package_id: UUID, **kwargs):
        self.calls.append(("quote", {"package_id": package_id, **kwargs}))
        return [
            {
                "carrierId": kwargs["carrier_id"] or uuid4(),
                "carrierName": "Manual carrier",
                "serviceId": kwargs["service_id"] or uuid4(),
                "serviceName": "Standard",
                "accountId": kwargs["account_id"],
                "amountMinor": 900,
                "currency": "USD",
                "estimatedDaysMin": 2,
                "estimatedDaysMax": 4,
                "quoteType": "calculated",
                "warnings": [],
            }
        ]

    async def create_waybill(self, tenant_id: UUID, package_id: UUID, **kwargs):
        self.calls.append(("create", {"package_id": package_id, **kwargs}))
        return _waybill(package_id, kwargs["carrier_id"], kwargs["service_id"])

    async def cancel_waybill(self, tenant_id: UUID, waybill_id: UUID, **kwargs):
        self.calls.append(("cancel", {"waybill_id": waybill_id, **kwargs}))
        return _waybill(
            uuid4(),
            uuid4(),
            uuid4(),
            waybill_id=waybill_id,
            status="cancelled",
            current=False,
        )


def _client(permissions: list[str]):
    service = FakeShippingService()
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(logistics.router, prefix="/api")
    app.dependency_overrides[require_session] = lambda: AuthSession(
        user_id=uuid4(), tenant_id=uuid4()
    )
    app.dependency_overrides[get_authenticated_user] = lambda: CurrentUser(
        id=uuid4(),
        name="Dispatcher",
        username="dispatcher",
        roles=[],
        permissions=permissions,
    )
    app.dependency_overrides[logistics_shipping._shipping_service] = lambda: service
    return TestClient(app), service


def test_dispatcher_can_quote_create_and_cancel_manual_waybill() -> None:
    package_id, carrier_id, service_id = uuid4(), uuid4(), uuid4()
    client, service = _client([LOGISTICS_VIEW, LOGISTICS_DISPATCH])
    with client:
        quote = client.post(
            f"/api/logistics/packages/{package_id}/shipping-quotes",
            json={"carrierId": str(carrier_id), "serviceId": str(service_id)},
        )
        created = client.post(
            f"/api/logistics/packages/{package_id}/waybills",
            json={
                "carrierId": str(carrier_id),
                "serviceId": str(service_id),
                "trackingNumber": "TRACK-123456",
            },
        )
        waybill_id = created.json()["id"]
        cancelled = client.post(
            f"/api/logistics/waybills/{waybill_id}/cancel",
            json={"versionId": 1, "reason": "重新选择服务"},
        )

    assert quote.status_code == 200
    assert quote.json()[0]["amountMinor"] == 900
    assert created.status_code == 201
    assert cancelled.json()["status"] == "cancelled"
    assert [item[0] for item in service.calls] == ["quote", "create", "cancel"]


def test_shipping_operations_require_dispatch_permission() -> None:
    client, service = _client([LOGISTICS_VIEW])
    with client:
        response = client.post(
            f"/api/logistics/packages/{uuid4()}/shipping-quotes", json={}
        )
    assert response.status_code == 403
    assert service.calls == []


def _waybill(
    package_id: UUID,
    carrier_id: UUID,
    service_id: UUID,
    *,
    waybill_id: UUID | None = None,
    status: str = "created",
    current: bool = True,
) -> dict[str, object]:
    now = datetime(2026, 8, 24, tzinfo=UTC)
    return {
        "id": waybill_id or uuid4(),
        "packageId": package_id,
        "carrierId": carrier_id,
        "serviceId": service_id,
        "accountId": None,
        "waybillNumber": "WB-20260824-0001",
        "externalWaybillId": None,
        "trackingNumberMasked": "TR****3456",
        "labelUrl": None,
        "status": status,
        "isCurrent": current,
        "createdAt": now,
        "updatedAt": now,
        "versionId": 1,
    }
