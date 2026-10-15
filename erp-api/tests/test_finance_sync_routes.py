from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from erp_api.core.errors import register_exception_handlers
from erp_api.core.permissions import FINANCE_VIEW, SYNC_TRIGGER
from erp_api.routers import finance
from erp_api.routers.auth import get_authenticated_user, require_session
from erp_api.services.auth import AuthSession, CurrentUser
from erp_api.services.finance_sync_repository import FinanceSyncResult


class FakeFinanceSyncService:
    def __init__(self) -> None:
        self.kwargs: dict[str, object] = {}

    async def sync(self, tenant_id: UUID, **kwargs):
        self.kwargs = kwargs
        return FinanceSyncResult(
            run_id=uuid4(),
            shop_id=kwargs["shop_id"],
            status="succeeded",
            fetched_count=3,
            written_count=3,
        )


def _client(service: FakeFinanceSyncService, permissions: list[str]) -> TestClient:
    tenant_id = uuid4()
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(finance.router, prefix="/api")
    app.dependency_overrides[require_session] = lambda: AuthSession(
        user_id=uuid4(), tenant_id=tenant_id
    )
    app.dependency_overrides[get_authenticated_user] = lambda: CurrentUser(
        id=uuid4(), name="Admin", username="admin", roles=[], permissions=permissions
    )
    app.dependency_overrides[finance._sync_service] = lambda: service
    return TestClient(app)


def test_finance_sync_requires_view_and_sync_permissions() -> None:
    service = FakeFinanceSyncService()
    payload = {
        "shopId": str(uuid4()),
        "mode": "backfill",
        "from": "2026-08-01T00:00:00Z",
        "to": "2026-08-21T00:00:00Z",
    }
    with _client(service, [FINANCE_VIEW]) as client:
        forbidden = client.post("/api/finance/sync", json=payload)
    with _client(service, [FINANCE_VIEW, SYNC_TRIGGER]) as client:
        allowed = client.post("/api/finance/sync", json=payload)

    assert forbidden.status_code == 403
    assert allowed.status_code == 200
    assert allowed.json()["writtenCount"] == 3
    assert service.kwargs["mode"] == "backfill"
