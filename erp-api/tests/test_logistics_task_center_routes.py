from types import SimpleNamespace
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from erp_api.core.permissions import LOGISTICS_VIEW
from erp_api.routers import logistics
from erp_api.routers.auth import get_authenticated_user, require_session
from erp_api.services.auth import AuthSession, CurrentUser


class FakeCenterRepository:
    def __init__(self) -> None:
        self.filters = None

    async def list_tasks(self, tenant_id: UUID, **kwargs):
        self.filters = kwargs
        return SimpleNamespace(items=[], total=0)

    async def list_shop_options(self, tenant_id: UUID):
        return [
            {
                "id": uuid4(),
                "shopName": "Demo shop",
                "platform": "tiktok",
                "platformShopId": "demo-shop",
            }
        ]


def _client(repository: FakeCenterRepository) -> TestClient:
    app = FastAPI()
    app.include_router(logistics.router, prefix="/api")
    app.dependency_overrides[require_session] = lambda: AuthSession(
        user_id=uuid4(), tenant_id=uuid4()
    )
    app.dependency_overrides[get_authenticated_user] = lambda: CurrentUser(
        id=uuid4(),
        name="Admin",
        username="admin",
        roles=[],
        permissions=[LOGISTICS_VIEW],
    )
    app.dependency_overrides[logistics._repository] = lambda: repository
    return TestClient(app)


def test_task_center_filters_shop_source_status_priority_and_created_time() -> None:
    repository = FakeCenterRepository()
    shop_id = uuid4()
    with _client(repository) as client:
        response = client.get(
            "/api/logistics/tasks",
            params={
                "shopId": str(shop_id),
                "sourceType": "sales_order",
                "status": "pending_review",
                "priority": "urgent",
                "createdFrom": "2026-08-01T00:00:00Z",
                "createdTo": "2026-09-01T00:00:00Z",
            },
        )

    assert response.status_code == 200
    assert repository.filters["shop_id"] == shop_id
    assert repository.filters["source_type"] == "sales_order"
    assert repository.filters["status"] == "pending_review"
    assert repository.filters["priority"] == "urgent"
    assert "warehouse" not in repository.filters


def test_logistics_shop_options_require_only_logistics_view() -> None:
    repository = FakeCenterRepository()
    with _client(repository) as client:
        response = client.get("/api/logistics/shops")

    assert response.status_code == 200
    assert response.json()[0]["shopName"] == "Demo shop"
