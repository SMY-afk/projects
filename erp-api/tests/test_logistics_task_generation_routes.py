from datetime import UTC, datetime
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from erp_api.core.errors import register_exception_handlers
from erp_api.core.permissions import LOGISTICS_OPERATE, LOGISTICS_VIEW
from erp_api.routers import logistics
from erp_api.routers.auth import get_authenticated_user, require_session
from erp_api.services.auth import AuthSession, CurrentUser


class FakeGenerationRepository:
    def __init__(self) -> None:
        self.last_call = None

    async def generate_sales_order_tasks(self, tenant_id, **kwargs):
        self.last_call = kwargs
        return [_task(), _task()]


def _task() -> dict[str, object]:
    now = datetime(2026, 8, 24, tzinfo=UTC)
    order_id, line_id = uuid4(), uuid4()
    return {
        "id": uuid4(),
        "taskNumber": f"LT-{uuid4().hex[:8]}",
        "sourceType": "sales_order",
        "direction": "forward",
        "sourceId": order_id,
        "sourceNumber": "ORDER-1",
        "orderId": order_id,
        "rmaId": None,
        "shopId": uuid4(),
        "priority": "normal",
        "status": "pending_review",
        "note": None,
        "createdByUserId": uuid4(),
        "createdAt": now,
        "updatedAt": now,
        "versionId": 1,
        "items": [
            {
                "id": uuid4(),
                "sourceLineId": line_id,
                "orderLineId": line_id,
                "platformProductId": None,
                "platformSkuId": None,
                "sellerSku": "SKU-1",
                "productName": "Product",
                "skuName": None,
                "plannedQuantity": 1,
                "packedQuantity": 0,
                "shippedQuantity": 0,
            }
        ],
        "operations": [],
        "reviews": [],
    }


def test_generate_multiple_tasks_from_one_sales_order_atomically() -> None:
    generation = FakeGenerationRepository()
    order_id = uuid4()
    line_ids = [uuid4(), uuid4()]
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(logistics.router, prefix="/api")
    app.dependency_overrides[require_session] = lambda: AuthSession(
        user_id=uuid4(), tenant_id=uuid4()
    )
    app.dependency_overrides[get_authenticated_user] = lambda: CurrentUser(
        id=uuid4(),
        name="Admin",
        username="admin",
        roles=[],
        permissions=[LOGISTICS_VIEW, LOGISTICS_OPERATE],
    )
    app.dependency_overrides[logistics._generation_repository] = lambda: generation
    with TestClient(app) as client:
        response = client.post(
            "/api/logistics/tasks/generate",
            json={
                "orderId": str(order_id),
                "tasks": [
                    {
                        "items": [
                            {"orderLineId": str(line_ids[0]), "plannedQuantity": 1}
                        ],
                        "priority": "urgent",
                    },
                    {
                        "items": [
                            {"orderLineId": str(line_ids[1]), "plannedQuantity": 2}
                        ]
                    },
                ],
            },
        )

    assert response.status_code == 201
    assert len(response.json()["items"]) == 2
    assert generation.last_call["order_id"] == order_id
    assert [plan.priority for plan in generation.last_call["plans"]] == [
        "urgent",
        "normal",
    ]
