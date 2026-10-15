from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from erp_api.core.permissions import AFFILIATE_CENTER_VIEW
from erp_api.routers import affiliate_center
from erp_api.routers.auth import get_authenticated_user, require_session
from erp_api.services.affiliate_center_capture_policy import (
    affiliate_center_capture_policy_contract,
)
from erp_api.services.affiliate_center_display_contract import (
    affiliate_center_display_contract,
)
from erp_api.services.auth import AuthSession, CurrentUser


class FakeRepository:
    async def list_shops(self, tenant_id):
        return [
            {
                "id": uuid4(),
                "shopName": "Demo Shop",
                "timezone": "America/Los_Angeles",
                "currency": "USD",
            }
        ]

    async def list_reports(self, tenant_id, shop_id):
        self.list_reports_call = (tenant_id, shop_id)
        return []

    async def list_metrics(self, tenant_id, shop_id, report_id, *, page, page_size):
        self.list_metrics_call = (
            tenant_id,
            shop_id,
            report_id,
            page,
            page_size,
        )
        return {"report": {}, "items": [], "page": page, "pageSize": page_size}


def _client(permissions: list[str]) -> tuple[TestClient, FakeRepository]:
    tenant_id, user_id = uuid4(), uuid4()
    app = FastAPI()
    app.include_router(affiliate_center.router, prefix="/api")
    repository = FakeRepository()
    app.state.affiliate_creator_repository = repository
    app.dependency_overrides[require_session] = lambda: AuthSession(user_id, tenant_id)
    app.dependency_overrides[get_authenticated_user] = lambda: CurrentUser(
        user_id, "Admin", "admin", [], permissions
    )
    return TestClient(app), repository


def test_excel_import_routes_are_not_registered() -> None:
    client, _ = _client([AFFILIATE_CENTER_VIEW])

    assert client.post("/api/affiliate-center/imports/preview").status_code == 404
    assert client.post("/api/affiliate-center/imports").status_code == 404


def test_report_list_requires_affiliate_center_view() -> None:
    assert _client([])[0].get("/api/affiliate-center/reports").status_code == 403


def test_report_list_requires_and_forwards_shop_scope() -> None:
    client, repository = _client([AFFILIATE_CENTER_VIEW])
    shop_id = uuid4()

    response = client.get(
        "/api/affiliate-center/reports", params={"shopId": str(shop_id)}
    )

    assert response.status_code == 200
    assert repository.list_reports_call[1] == shop_id


def test_creator_page_requires_and_forwards_shop_scope() -> None:
    client, repository = _client([AFFILIATE_CENTER_VIEW])
    shop_id, report_id = uuid4(), uuid4()

    response = client.get(
        f"/api/affiliate-center/reports/{report_id}/creators",
        params={"shopId": str(shop_id), "page": 2, "pageSize": 25},
    )

    assert response.status_code == 200
    assert repository.list_metrics_call[1:] == (shop_id, report_id, 2, 25)


def test_resources_keep_two_independent_resource_keys() -> None:
    response = _client([AFFILIATE_CENTER_VIEW])[0].get(
        "/api/affiliate-center/resources"
    )

    assert response.status_code == 200
    body = response.json()
    assert [item["key"] for item in body["items"]] == ["creators", "videos"]
    assert body["queryDimensions"] == [
        "shopId",
        "windowStart",
        "windowEnd",
        "shopTimezone",
        "currency",
        "filters",
    ]
    assert body["windowSemantics"] == "inclusive_shop_local_dates"
    assert body["display"] == affiliate_center_display_contract()
    assert body["capturePolicy"] == affiliate_center_capture_policy_contract()


def test_shops_route_is_preserved() -> None:
    response = _client([AFFILIATE_CENTER_VIEW])[0].get("/api/affiliate-center/shops")

    assert response.status_code == 200
    assert response.json()["items"][0]["shopName"] == "Demo Shop"
