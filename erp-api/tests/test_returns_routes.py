from datetime import UTC, datetime
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from erp_api.core.errors import register_exception_handlers
from erp_api.core.permissions import RETURNS_MANAGE, RETURNS_VIEW
from erp_api.routers import returns
from erp_api.routers.auth import get_authenticated_user, require_session
from erp_api.services.auth import AuthSession, CurrentUser


class FakeReturnsRepository:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def get_eligibility(self, tenant_id, order_reference):
        self.calls.append(("eligibility", {"order_reference": order_reference}))
        return {
            "orderId": uuid4(),
            "orderNumber": order_reference,
            "shopId": uuid4(),
            "items": [],
        }

    async def create_request(self, tenant_id, **kwargs):
        self.calls.append(("create", kwargs))
        return _request_record(kwargs["order_id"])

    async def review_request(self, tenant_id, **kwargs):
        self.calls.append(("review", kwargs))
        return _request_record(uuid4(), approved=kwargs["decision"] == "approve")

    async def list_requests(self, tenant_id, **kwargs):
        self.calls.append(("list", kwargs))
        return type("Page", (), {"items": [], "total": 0})()

    async def get_request(self, tenant_id, request_id):
        return None


class FakeReturnsSyncService:
    def __init__(self) -> None:
        self.calls = []

    async def sync(self, tenant_id, *, shop_id):
        self.calls.append((tenant_id, shop_id))
        return {
            "shopId": shop_id,
            "fetchedCount": 20,
            "upsertedCount": 3,
            "unmatchedOrderCount": 17,
            "unmatchedLineCount": 0,
        }


def _request_record(order_id, approved: bool = False):
    now = datetime(2026, 8, 25, tzinfo=UTC)
    return {
        "id": uuid4(),
        "requestNumber": "RR-20260825-ABC123",
        "orderId": order_id,
        "orderNumber": "ORDER-1",
        "shopId": uuid4(),
        "requestType": "return",
        "status": "approved" if approved else "pending_review",
        "reasonCode": "changed_mind",
        "customerNote": None,
        "createdByUserId": uuid4(),
        "reviewedByUserId": uuid4() if approved else None,
        "reviewNote": None,
        "reviewedAt": now if approved else None,
        "createdAt": now,
        "updatedAt": now,
        "versionId": 1,
        "items": [],
        "rma": (
            {
                "id": uuid4(),
                "rmaNumber": "RMA-20260825-ABC123",
                "status": "open",
                "reverseTaskId": uuid4(),
                "generatedAt": now,
            }
            if approved
            else None
        ),
    }


def _client(
    repository: FakeReturnsRepository,
    sync_service: FakeReturnsSyncService | None = None,
) -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(returns.router, prefix="/api")
    app.dependency_overrides[require_session] = lambda: AuthSession(
        user_id=uuid4(), tenant_id=uuid4()
    )
    app.dependency_overrides[get_authenticated_user] = lambda: CurrentUser(
        id=uuid4(),
        name="Admin",
        username="admin",
        roles=[],
        permissions=[RETURNS_VIEW, RETURNS_MANAGE],
    )
    app.dependency_overrides[returns._repository] = lambda: repository
    if sync_service is not None:
        app.dependency_overrides[returns._sync_service] = lambda: sync_service
    return TestClient(app)


def test_create_return_request_passes_original_order_and_quantities() -> None:
    repository = FakeReturnsRepository()
    order_id, line_id = uuid4(), uuid4()
    with _client(repository) as client:
        response = client.post(
            "/api/returns",
            json={
                "orderId": str(order_id),
                "requestType": "return",
                "reasonCode": "changed_mind",
                "items": [
                    {
                        "orderLineId": str(line_id),
                        "requestedQuantity": 1,
                        "reasonCode": "changed_mind",
                    }
                ],
            },
        )
    assert response.status_code == 201
    assert repository.calls[0][1]["order_id"] == order_id
    assert repository.calls[0][1]["items"][0].requested_quantity == 1


def test_approve_request_returns_rma_and_reverse_task_link() -> None:
    repository = FakeReturnsRepository()
    request_id = uuid4()
    with _client(repository) as client:
        response = client.post(
            f"/api/returns/{request_id}/review",
            json={"decision": "approve", "note": "符合退货条件", "versionId": 1},
        )
    assert response.status_code == 200
    assert response.json()["rma"]["reverseTaskId"]
    assert repository.calls[0][1]["request_id"] == request_id


def test_sync_imports_platform_records_without_rma_or_waybill_input() -> None:
    repository = FakeReturnsRepository()
    service = FakeReturnsSyncService()
    shop_id = uuid4()
    with _client(repository, service) as client:
        response = client.post("/api/returns/sync", json={"shopId": str(shop_id)})

    assert response.status_code == 200
    assert response.json() == {
        "shopId": str(shop_id),
        "fetchedCount": 20,
        "upsertedCount": 3,
        "unmatchedOrderCount": 17,
        "unmatchedLineCount": 0,
    }
    assert service.calls[0][1] == shop_id


def test_list_return_requests_passes_all_center_filters() -> None:
    repository = FakeReturnsRepository()
    shop_id = uuid4()
    with _client(repository) as client:
        response = client.get(
            "/api/returns/requests",
            params={
                "shopId": str(shop_id),
                "requestType": "return",
                "status": "approved",
                "reason": "damaged",
                "appliedFrom": "2026-08-01T00:00:00Z",
                "appliedTo": "2026-08-25T23:59:59Z",
                "rma": "RMA-20260825",
            },
        )

    assert response.status_code == 200
    _, values = repository.calls[0]
    assert values["shop_id"] == shop_id
    assert values["request_type"] == "return"
    assert values["status"] == "approved"
    assert values["reason"] == "damaged"
    assert values["applied_from"] == datetime(2026, 8, 1, tzinfo=UTC)
    assert values["applied_to"] == datetime(2026, 8, 25, 23, 59, 59, tzinfo=UTC)
    assert values["rma"] == "RMA-20260825"


def test_list_return_requests_rejects_an_inverted_application_window() -> None:
    repository = FakeReturnsRepository()
    with _client(repository) as client:
        response = client.get(
            "/api/returns/requests",
            params={
                "appliedFrom": "2026-08-25T00:00:00Z",
                "appliedTo": "2026-08-01T00:00:00Z",
            },
        )

    assert response.status_code == 422
    assert repository.calls == []
