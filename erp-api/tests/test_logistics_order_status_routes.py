from datetime import UTC, datetime
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from erp_api.core.permissions import LOGISTICS_VIEW, SYNC_TRIGGER
from erp_api.routers import logistics
from erp_api.routers.auth import get_authenticated_user, require_session
from erp_api.routers.logistics_order_status import _service
from erp_api.services.auth import AuthSession, CurrentUser


def _app(permissions: list[str]):
    app = FastAPI()
    app.include_router(logistics.router, prefix="/api")
    tenant_id = uuid4()
    user_id = uuid4()
    order_id = uuid4()
    shop_id = uuid4()
    calls = []

    class Service:
        async def sync_page(self, current_tenant, **params):
            calls.append(("sync", current_tenant, params))
            return {
                "items": [],
                "total": 0,
                "page": params["page"],
                "pageSize": params["page_size"],
            }

        async def export_orders(
            self,
            current_tenant,
            current_shop,
            order_number=None,
            category=None,
            alert=None,
            alert_phase="overdue",
        ):
            calls.append(
                ("export", current_tenant, current_shop, order_number, category, alert, alert_phase)
            )
            return {"items": [], "total": 0, "page": 1, "pageSize": 100_000}

        async def list_orders(self, current_tenant, **params):
            calls.append(("list", current_tenant, params))
            return {
                "items": [
                    {
                        "id": order_id,
                        "shopId": shop_id,
                        "shopName": "Shop",
                        "orderNumber": "ORDER-1",
                        "orderCreatedAt": datetime.now(UTC),
                        "platformStatus": "IN_TRANSIT",
                        "platformUpdatedAt": datetime.now(UTC),
                        "erpSyncedAt": datetime.now(UTC),
                        "packages": [],
                    }
                ],
                "total": 1,
                "page": 1,
                "pageSize": 20,
            }

        async def refresh(self, current_tenant, current_order):
            calls.append(("refresh", current_tenant, current_order))
            return {
                "orderId": order_id,
                "trackingStatus": "delivered",
                "checkedAt": datetime.now(UTC),
                "events": [],
                "packages": [],
                "platformStatus": "COMPLETED",
                "platformUpdatedAt": datetime.now(UTC),
                "orderCreatedAt": datetime.now(UTC),
                "shippedAt": None,
                "firstLocationAt": None,
                "deliveredAt": None,
                "shippedDescription": None,
                "firstLocationDescription": None,
                "deliveredDescription": None,
                "milestoneNotes": [],
            }

    app.dependency_overrides[require_session] = lambda: AuthSession(user_id, tenant_id)
    app.dependency_overrides[get_authenticated_user] = lambda: CurrentUser(
        user_id, "Operator", "operator", [], permissions
    )
    app.dependency_overrides[_service] = Service
    return app, tenant_id, order_id, calls


def test_list_and_single_order_refresh_require_logistics_view() -> None:
    app, tenant_id, order_id, calls = _app([LOGISTICS_VIEW])
    with TestClient(app) as client:
        listed = client.get("/api/logistics/status/orders?page=1&pageSize=20")
        refreshed = client.post(f"/api/logistics/status/orders/{order_id}/refresh")
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert refreshed.status_code == 200
    assert refreshed.json()["trackingStatus"] == "delivered"
    assert calls == [
        (
            "list",
            tenant_id,
            {
                "page": 1,
                "page_size": 20,
                "shop_id": None,
                "order_number": None,
                "category": None,
                "alert": None,
                "alert_phase": "overdue",
            },
        ),
        ("refresh", tenant_id, order_id),
    ]

    app, _, order_id, calls = _app([])
    with TestClient(app) as client:
        assert client.get("/api/logistics/status/orders").status_code == 403
        assert (
            client.post(f"/api/logistics/status/orders/{order_id}/refresh").status_code
            == 403
        )
    assert calls == []


def test_export_respects_permission_and_selected_shop() -> None:
    app, tenant_id, _, calls = _app([LOGISTICS_VIEW])
    shop_id = uuid4()
    with TestClient(app) as client:
        result = client.get(f"/api/logistics/status/export-data?shopId={shop_id}")
    assert result.status_code == 200
    assert calls == [("export", tenant_id, shop_id, None, None, None, "overdue")]
    app, _, _, calls = _app([])
    with TestClient(app) as client:
        assert client.get("/api/logistics/status/export-data").status_code == 403
    assert calls == []


def test_order_number_filter_is_trimmed_for_list_and_export() -> None:
    app, tenant_id, _, calls = _app([LOGISTICS_VIEW])
    shop_id = uuid4()
    params = {"shopId": str(shop_id), "orderNumber": " 982740775181726442 "}
    with TestClient(app) as client:
        assert (
            client.get("/api/logistics/status/orders", params=params).status_code == 200
        )
        assert (
            client.get("/api/logistics/status/export-data", params=params).status_code
            == 200
        )
    assert calls == [
        (
            "list",
            tenant_id,
            {
                "page": 1,
                "page_size": 20,
                "shop_id": shop_id,
                "order_number": "982740775181726442",
                "category": None,
                "alert": None,
                "alert_phase": "overdue",
            },
        ),
        ("export", tenant_id, shop_id, "982740775181726442", None, None, "overdue"),
    ]


def test_category_is_validated_and_forwarded_to_list_and_export():
    app, _, _, calls = _app([LOGISTICS_VIEW])
    with TestClient(app) as client:
        assert (
            client.get(
                "/api/logistics/status/orders?category=partial_shipping"
            ).status_code
            == 200
        )
        assert (
            client.get(
                "/api/logistics/status/export-data?category=delivered"
            ).status_code
            == 200
        )
        assert (
            client.get("/api/logistics/status/orders?category=invalid").status_code
            == 422
        )
    assert calls[0][2]["category"] == "partial_shipping"
    assert calls[1][-3] == "delivered"


def test_realtime_sync_requires_sync_permission_and_preserves_category_scope():
    app, _, _, calls = _app([LOGISTICS_VIEW])
    with TestClient(app) as client:
        assert client.post("/api/logistics/status/sync").status_code == 403
    assert calls == []
    app, tenant, _, calls = _app([LOGISTICS_VIEW, SYNC_TRIGGER])
    with TestClient(app) as client:
        assert (
            client.post(
                "/api/logistics/status/sync?category=delivered&pageSize=20"
            ).status_code
            == 200
        )
    assert calls[0] == (
        "sync",
        tenant,
        {
            "page": 1,
            "page_size": 20,
            "shop_id": None,
            "order_number": None,
            "category": "delivered",
            "alert": None,
                "alert_phase": "overdue",
        },
    )


def test_warning_filter_is_shared_by_list_and_export_and_rejects_invalid_key():
    app, _, _, calls = _app([LOGISTICS_VIEW])
    with TestClient(app) as client:
        assert (
            client.get("/api/logistics/status/orders?alert=undelivered_77h").status_code
            == 200
        )
        assert (
            client.get(
                "/api/logistics/status/export-data?alert=undelivered_77h"
            ).status_code
            == 200
        )
        assert (
            client.get("/api/logistics/status/orders?alert=invalid").status_code == 422
        )
    assert calls[0][2]["alert"] == calls[1][-2] == "undelivered_77h"


def test_early_phase_is_forwarded_identically_and_invalid_phase_rejected():
    app, _, _, calls = _app([LOGISTICS_VIEW])
    with TestClient(app) as client:
        params = {"alert": "unshipped_48h", "alertPhase": "upcoming"}
        assert client.get("/api/logistics/status/orders", params=params).status_code == 200
        assert client.get("/api/logistics/status/export-data", params=params).status_code == 200
        assert client.get("/api/logistics/status/orders?alertPhase=invalid").status_code == 422
    assert calls[0][2]["alert_phase"] == calls[1][-1] == "upcoming"
