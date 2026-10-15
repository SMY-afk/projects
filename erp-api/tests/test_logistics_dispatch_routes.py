from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from erp_api.core.errors import register_exception_handlers
from erp_api.core.permissions import LOGISTICS_DISPATCH, LOGISTICS_VIEW
from erp_api.routers import logistics, logistics_dispatch
from erp_api.routers.auth import get_authenticated_user, require_session
from erp_api.services.auth import AuthSession, CurrentUser


class FakeDispatchRepository:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.callback_id: UUID | None = None

    async def dispatch(self, tenant_id: UUID, package_id: UUID, **kwargs):
        self.calls.append({"package_id": package_id, **kwargs})
        return _response(
            package_id,
            kwargs["waybill_id"],
            kwargs["actual_quantities"],
            callback_id=self.callback_id,
        )


class FakeQueue:
    def __init__(self) -> None:
        self.calls = []

    async def enqueue_job(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return object()


class FakeOutboxRepository:
    def __init__(self) -> None:
        self.task_id = None

    async def list_for_task(self, tenant_id, task_id):
        self.task_id = task_id
        return []


def _client(permissions: list[str]):
    repository = FakeDispatchRepository()
    queue = FakeQueue()
    app = FastAPI()
    app.state.arq_queue = queue
    app.state.platform_fulfillment_outbox_repository = FakeOutboxRepository()
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
    app.dependency_overrides[logistics_dispatch._repository] = lambda: repository
    return TestClient(app), repository, queue


def test_platform_callback_status_requires_view_permission() -> None:
    task_id = uuid4()
    client, _, _ = _client([LOGISTICS_VIEW])
    with client:
        response = client.get(
            f"/api/logistics/tasks/{task_id}/platform-fulfillment-callbacks"
        )

    assert response.status_code == 200
    assert response.json() == []


def test_dispatch_requires_versions_waybill_and_actual_quantities() -> None:
    package_id, waybill_id, item_id = uuid4(), uuid4(), uuid4()
    client, repository, _ = _client([LOGISTICS_VIEW, LOGISTICS_DISPATCH])
    with client:
        response = client.post(
            f"/api/logistics/packages/{package_id}/dispatch",
            json={
                "packageVersionId": 3,
                "waybillId": str(waybill_id),
                "waybillVersionId": 2,
                "items": [{"taskItemId": str(item_id), "quantity": 2}],
                "note": "复核无误",
            },
        )

    assert response.status_code == 200
    assert response.json()["taskStatus"] == "shipped"
    assert repository.calls[0]["package_version_id"] == 3
    assert repository.calls[0]["actual_quantities"] == [(item_id, 2)]


def test_dispatch_requires_dispatch_permission() -> None:
    client, repository, _ = _client([LOGISTICS_VIEW])
    with client:
        response = client.post(
            f"/api/logistics/packages/{uuid4()}/dispatch",
            json={
                "packageVersionId": 1,
                "waybillId": str(uuid4()),
                "waybillVersionId": 1,
                "items": [{"taskItemId": str(uuid4()), "quantity": 1}],
            },
        )
    assert response.status_code == 403
    assert repository.calls == []


def test_dispatch_enqueues_platform_callback_only_after_repository_returns() -> None:
    package_id, waybill_id, item_id = uuid4(), uuid4(), uuid4()
    client, repository, queue = _client([LOGISTICS_VIEW, LOGISTICS_DISPATCH])
    repository.callback_id = uuid4()

    with client:
        response = client.post(
            f"/api/logistics/packages/{package_id}/dispatch",
            json={
                "packageVersionId": 1,
                "waybillId": str(waybill_id),
                "waybillVersionId": 1,
                "items": [{"taskItemId": str(item_id), "quantity": 1}],
            },
        )

    assert response.status_code == 200
    assert response.json()["platformCallbackQueued"] is True
    assert queue.calls[0][0][0] == "process_platform_fulfillment_job"
    assert queue.calls[0][0][2] == str(repository.callback_id)


def _response(package_id, waybill_id, quantities, *, callback_id=None):
    from tests.test_logistics_shipping_adapter_routes import _waybill
    from tests.test_logistics_shipping_routes import _package

    task_id = uuid4()
    package = _package(task_id, 1, status="shipped", package_id=package_id)
    waybill = _waybill(
        package_id, uuid4(), uuid4(), waybill_id=waybill_id, status="shipped"
    )
    return {
        "package": package,
        "waybill": waybill,
        "taskId": task_id,
        "taskStatus": "shipped",
        "taskVersionId": 4,
        "shippedItems": [
            {"taskItemId": item_id, "quantity": quantity}
            for item_id, quantity in quantities
        ],
        "platformCallbackId": callback_id,
    }
