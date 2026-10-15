from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from erp_api.core.permissions import LOGISTICS_MANAGE, LOGISTICS_OPERATE, LOGISTICS_VIEW
from erp_api.routers import logistics
from erp_api.routers.auth import get_authenticated_user, require_session
from erp_api.routers.logistics_exceptions import _platform_sync_service, _service
from erp_api.services.auth import AuthSession, CurrentUser


class FakeExceptionService:
    def __init__(self) -> None:
        self.calls = []

    async def list_exceptions(self, tenant_id, **filters):
        self.calls.append(("list", filters))
        return SimpleNamespace(items=[], total=0)

    async def claim(self, tenant_id, exception_id, **values):
        self.calls.append(("claim", values))
        return _record(exception_id, status="claimed", version_id=2)

    async def add_note(self, tenant_id, exception_id, **values):
        self.calls.append(("note", values))
        return _record(exception_id, version_id=2)

    async def escalate(self, tenant_id, exception_id, **values):
        self.calls.append(("escalate", values))
        return _record(
            exception_id, status="escalated", severity="critical", version_id=2
        )

    async def resolve(self, tenant_id, exception_id, **values):
        self.calls.append(("resolve", values))
        return _record(exception_id, status="resolved", version_id=2)

    async def close(self, tenant_id, exception_id, **values):
        self.calls.append(("close", values))
        return _record(exception_id, status="closed", version_id=2)

    async def scan_tenant(self, tenant_id):
        return {"scanned": 4, "detected": 2}


def _record(exception_id, *, status="open", severity="medium", version_id=1):
    return {
        "id": exception_id,
        "exceptionNumber": "LEX-20260824-0001",
        "waybillId": uuid4(),
        "packageId": uuid4(),
        "taskId": uuid4(),
        "taskNumber": "LT-1",
        "sourceNumber": "ORDER-1",
        "carrierName": "Manual",
        "trackingNumberMasked": "****1234",
        "exceptionType": "stalled",
        "status": status,
        "severity": severity,
        "source": "scheduled_scan",
        "title": "运输滞留",
        "description": "72 小时无新轨迹",
        "assignedToUserId": None,
        "resolution": None,
        "firstDetectedAt": "2026-08-24T10:00:00Z",
        "lastDetectedAt": "2026-08-24T10:00:00Z",
        "occurrenceCount": 1,
        "resolvedAt": None,
        "closedAt": None,
        "updatedAt": "2026-08-24T10:00:00Z",
        "versionId": version_id,
        "actions": [],
    }


def _app(service, permissions):
    app = FastAPI()
    app.include_router(logistics.router, prefix="/api")
    tenant_id = uuid4()
    user_id = uuid4()
    app.dependency_overrides[require_session] = lambda: AuthSession(user_id, tenant_id)
    app.dependency_overrides[get_authenticated_user] = lambda: CurrentUser(
        user_id, "Operator", "operator", [], permissions
    )
    app.dependency_overrides[_service] = lambda: service
    app.dependency_overrides[_platform_sync_service] = lambda: SimpleNamespace(
        sync_tenant=lambda *args, **kwargs: None
    )
    return app


def test_list_and_operator_actions_use_existing_logistics_permissions() -> None:
    service = FakeExceptionService()
    exception_id = uuid4()
    with TestClient(_app(service, [LOGISTICS_VIEW, LOGISTICS_OPERATE])) as client:
        listed = client.get("/api/logistics/exceptions?status=open&page=1&pageSize=20")
        claimed = client.post(
            f"/api/logistics/exceptions/{exception_id}/claim", json={"versionId": 1}
        )
        noted = client.post(
            f"/api/logistics/exceptions/{exception_id}/notes",
            json={"versionId": 2, "note": "已联系物流商"},
        )
        resolved = client.post(
            f"/api/logistics/exceptions/{exception_id}/resolve",
            json={"versionId": 2, "resolution": "物流商确认恢复运输"},
        )

    assert listed.status_code == 200
    assert claimed.json()["status"] == "claimed"
    assert noted.status_code == 200
    assert resolved.json()["status"] == "resolved"


def test_escalate_close_and_manual_detection_require_manage_permission() -> None:
    service = FakeExceptionService()
    exception_id = uuid4()
    with TestClient(
        _app(service, [LOGISTICS_VIEW, LOGISTICS_OPERATE, LOGISTICS_MANAGE])
    ) as client:
        escalated = client.post(
            f"/api/logistics/exceptions/{exception_id}/escalate",
            json={"versionId": 1, "severity": "critical", "note": "升级主管"},
        )
        closed = client.post(
            f"/api/logistics/exceptions/{exception_id}/close",
            json={"versionId": 2, "note": "复盘完成"},
        )
        detected = client.post("/api/logistics/exceptions/detect")

    assert escalated.json()["status"] == "escalated"
    assert closed.json()["status"] == "closed"
    assert detected.json() == {"scanned": 4, "detected": 2}


def test_platform_sync_requires_manage_permission_and_returns_counts() -> None:
    service = FakeExceptionService()

    class FakePlatformSyncService:
        async def sync_tenant(self, tenant_id, *, shop_id=None, actor_user_id=None):
            return {
                "shopsScanned": 1,
                "ordersScanned": 15,
                "packagesSynced": 15,
                "trackingEventsSynced": 134,
                "failedOrders": 0,
                "exceptionsScanned": 15,
                "exceptionsDetected": 2,
            }

    app = _app(service, [LOGISTICS_VIEW, LOGISTICS_MANAGE])
    app.dependency_overrides[_platform_sync_service] = FakePlatformSyncService
    with TestClient(app) as client:
        response = client.post("/api/logistics/exceptions/sync-platform")

    assert response.status_code == 200
    assert response.json()["exceptionsDetected"] == 2
