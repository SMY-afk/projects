from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from erp_api.core.errors import register_exception_handlers
from erp_api.core.permissions import LOGISTICS_OPERATE, LOGISTICS_VIEW
from erp_api.routers import logistics, logistics_workflow
from erp_api.routers.auth import get_authenticated_user, require_session
from erp_api.services.auth import AuthSession, CurrentUser


def _task() -> dict[str, object]:
    task_id = uuid4()
    order_id = uuid4()
    line_id = uuid4()
    timestamp = datetime(2026, 8, 24, 4, 0, tzinfo=UTC)
    return {
        "id": task_id,
        "taskNumber": "LT-20260824-ABC123",
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
        "createdAt": timestamp,
        "updatedAt": timestamp,
        "versionId": 1,
        "items": [
            {
                "id": uuid4(),
                "sourceLineId": line_id,
                "orderLineId": line_id,
                "platformProductId": "product-1",
                "platformSkuId": "sku-1",
                "sellerSku": "SELLER-SKU-1",
                "productName": "Product One",
                "skuName": "Blue",
                "plannedQuantity": 2,
                "packedQuantity": 0,
                "shippedQuantity": 0,
            }
        ],
        "operations": [],
        "reviews": [],
    }


class FakeLogisticsRepository:
    def __init__(self) -> None:
        self.task = _task()
        self.last_call: tuple[str, dict[str, object]] | None = None

    async def list_tasks(self, tenant_id: UUID, **kwargs):
        self.last_call = ("list", kwargs)
        return SimpleNamespace(items=[self.task], total=1)

    async def list_shop_options(self, tenant_id: UUID):
        return [
            {
                "id": self.task["shopId"],
                "shopName": "Demo shop",
                "platform": "tiktok",
                "platformShopId": "demo-shop",
            }
        ]

    async def get_task(self, tenant_id: UUID, task_id: UUID):
        self.last_call = ("get", {"task_id": task_id})
        return self.task if task_id == self.task["id"] else None

    async def get_order_context(self, tenant_id: UUID, task_id: UUID):
        return {
            "orderId": self.task["orderId"],
            "orderNumber": self.task["sourceNumber"],
            "shopId": self.task["shopId"],
            "shopName": "Demo shop",
            "status": "paid",
            "externalStatus": "AWAITING_SHIPMENT",
            "buyerUsernameMasked": "b***r",
            "placedAt": self.task["createdAt"],
            "maskedRecipient": None,
        }

    async def create_sales_order_task(self, tenant_id: UUID, **kwargs):
        self.last_call = ("create", kwargs)
        return self.task


class FakeTaskGenerationRepository:
    def __init__(self, task: dict[str, object]) -> None:
        self.task = task
        self.last_call: dict[str, object] | None = None

    async def generate_sales_order_tasks(self, tenant_id: UUID, **kwargs):
        self.last_call = kwargs
        return [self.task, {**self.task, "id": uuid4(), "taskNumber": "LT-SECOND"}]


class FakeWorkflowRepository:
    def __init__(self, task: dict[str, object]) -> None:
        self.task = task
        self.last_call: tuple[str, dict[str, object]] | None = None

    async def confirm_picking_completed(self, tenant_id: UUID, task_id: UUID, **kwargs):
        self.last_call = ("picking", {"task_id": task_id, **kwargs})
        return self.task if task_id == self.task["id"] else None

    async def record_review(self, tenant_id: UUID, task_id: UUID, **kwargs):
        self.last_call = ("review", {"task_id": task_id, **kwargs})
        return self.task if task_id == self.task["id"] else None

    async def resolve_scan(self, tenant_id: UUID, **kwargs):
        self.last_call = ("scan", kwargs)
        return {
            "code": kwargs["code"],
            "matchType": "task_item",
            "tasks": [],
            "items": [
                {
                    "taskId": self.task["id"],
                    "taskNumber": self.task["taskNumber"],
                    "sourceNumber": self.task["sourceNumber"],
                    "status": self.task["status"],
                    "taskItemId": self.task["items"][0]["id"],
                    "sellerSku": "SELLER-SKU-1",
                    "platformSkuId": "sku-1",
                    "productName": "Product One",
                    "skuName": "Blue",
                    "plannedQuantity": 2,
                }
            ],
        }


def _client(repository: FakeLogisticsRepository, permissions: list[str]) -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(logistics.router, prefix="/api")
    app.dependency_overrides[require_session] = lambda: AuthSession(
        user_id=uuid4(), tenant_id=uuid4()
    )
    app.dependency_overrides[get_authenticated_user] = lambda: CurrentUser(
        id=uuid4(), name="Admin", username="admin", roles=[], permissions=permissions
    )
    app.dependency_overrides[logistics._repository] = lambda: repository
    app.dependency_overrides[logistics._generation_repository] = lambda: (
        FakeTaskGenerationRepository(repository.task)
    )
    app.state.fake_workflow_repository = FakeWorkflowRepository(repository.task)
    app.dependency_overrides[logistics_workflow._workflow_repository] = lambda: (
        app.state.fake_workflow_repository
    )
    app.dependency_overrides[logistics_workflow._task_repository] = lambda: repository
    return TestClient(app)


def test_logistics_task_list_and_detail_require_view_permission() -> None:
    repository = FakeLogisticsRepository()
    task_id = repository.task["id"]
    with _client(repository, []) as client:
        forbidden = client.get("/api/logistics/tasks")
    with _client(repository, [LOGISTICS_VIEW]) as client:
        listing = client.get("/api/logistics/tasks?page=1&pageSize=20")
        detail = client.get(f"/api/logistics/tasks/{task_id}")
        context = client.get(f"/api/logistics/tasks/{task_id}/order-context")

    assert forbidden.status_code == 403
    assert listing.status_code == 200
    assert listing.json()["total"] == 1
    assert detail.status_code == 200
    assert detail.json()["sourceType"] == "sales_order"
    assert context.status_code == 200
    assert context.json()["maskedRecipient"] is None


def test_create_task_accepts_sales_order_lines_and_requires_operate_permission() -> (
    None
):
    repository = FakeLogisticsRepository()
    payload = {
        "sourceType": "sales_order",
        "sourceId": str(uuid4()),
        "items": [{"sourceLineId": str(uuid4()), "plannedQuantity": 2}],
        "note": "Priority shipment",
    }
    with _client(repository, [LOGISTICS_VIEW]) as client:
        forbidden = client.post("/api/logistics/tasks", json=payload)
    with _client(repository, [LOGISTICS_VIEW, LOGISTICS_OPERATE]) as client:
        created = client.post("/api/logistics/tasks", json=payload)

    assert forbidden.status_code == 403
    assert created.status_code == 201
    assert repository.last_call is not None
    assert repository.last_call[0] == "create"
    assert repository.last_call[1]["order_id"] == UUID(payload["sourceId"])


def test_transfer_order_source_is_not_accepted() -> None:
    repository = FakeLogisticsRepository()
    with _client(repository, [LOGISTICS_VIEW, LOGISTICS_OPERATE]) as client:
        response = client.post(
            "/api/logistics/tasks",
            json={
                "sourceType": "transfer_order",
                "sourceId": str(uuid4()),
                "items": [{"sourceLineId": str(uuid4()), "plannedQuantity": 1}],
            },
        )

    assert response.status_code == 422
    assert repository.last_call is None


def test_picking_completion_and_scan_require_operate_permission() -> None:
    repository = FakeLogisticsRepository()
    task_id = repository.task["id"]
    with _client(repository, [LOGISTICS_VIEW]) as client:
        forbidden = client.post(
            f"/api/logistics/tasks/{task_id}/picking-completion", json={}
        )
    client = _client(repository, [LOGISTICS_VIEW, LOGISTICS_OPERATE])
    workflow = client.app.state.fake_workflow_repository
    with client:
        completed = client.post(
            f"/api/logistics/tasks/{task_id}/picking-completion",
            json={"note": "Manual picking completed"},
        )
        scanned = client.post(
            "/api/logistics/scans/resolve",
            json={"code": "SELLER-SKU-1", "taskId": str(task_id)},
        )

    assert forbidden.status_code == 403
    assert completed.status_code == 200
    assert scanned.status_code == 200
    assert scanned.json()["items"][0]["taskItemId"] == str(
        repository.task["items"][0]["id"]
    )
    assert workflow.last_call[0] == "scan"


def test_review_records_item_quantities_and_difference_reason() -> None:
    repository = FakeLogisticsRepository()
    task_id = repository.task["id"]
    client = _client(repository, [LOGISTICS_VIEW, LOGISTICS_OPERATE])
    workflow = client.app.state.fake_workflow_repository
    with client:
        response = client.post(
            f"/api/logistics/tasks/{task_id}/reviews",
            json={
                "items": [
                    {
                        "taskItemId": str(repository.task["items"][0]["id"]),
                        "actualQuantity": 1,
                        "differenceReason": "shortage",
                    }
                ],
                "note": "One unit missing",
            },
        )

    assert response.status_code == 200
    assert workflow.last_call is not None
    assert workflow.last_call[0] == "review"
    assert workflow.last_call[1]["items"][0].difference_reason == "shortage"
