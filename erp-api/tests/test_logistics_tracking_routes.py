from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from erp_api.core.permissions import LOGISTICS_VIEW
from erp_api.routers import logistics, logistics_tracking
from erp_api.routers.auth import get_authenticated_user, require_session
from erp_api.services.auth import AuthSession, CurrentUser


class FakeTrackingService:
    async def receive_webhook(self, tenant_id, carrier_code, body, **kwargs):
        return SimpleNamespace(
            received=2,
            accepted=1,
            duplicates=1,
            ignored=0,
            events=[
                SimpleNamespace(event_id=uuid4()),
                SimpleNamespace(event_id=uuid4()),
            ],
        )


class FakeTrackingRepository:
    async def list_events(self, tenant_id, waybill_id):
        return []


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(logistics.router, prefix="/api")
    app.include_router(logistics_tracking.webhook_router, prefix="/api/v1")
    app.dependency_overrides[logistics_tracking._service] = FakeTrackingService
    app.dependency_overrides[logistics_tracking._repository] = FakeTrackingRepository
    app.dependency_overrides[require_session] = lambda: AuthSession(
        user_id=uuid4(), tenant_id=uuid4()
    )
    app.dependency_overrides[get_authenticated_user] = lambda: CurrentUser(
        id=uuid4(),
        name="Viewer",
        username="viewer",
        roles=[],
        permissions=[LOGISTICS_VIEW],
    )
    return app


def test_carrier_webhook_returns_dedupe_summary() -> None:
    with TestClient(_app()) as client:
        response = client.post(
            f"/api/v1/webhooks/logistics/{uuid4()}/DHL",
            content=b"{}",
            headers={"X-Carrier-Signature": "signature", "X-Carrier-Timestamp": "1"},
        )

    assert response.status_code == 202
    assert response.json()["accepted"] == 1
    assert response.json()["duplicates"] == 1
    assert len(response.json()["eventIds"]) == 2


def test_tracking_timeline_uses_logistics_view_permission() -> None:
    with TestClient(_app()) as client:
        response = client.get(f"/api/logistics/waybills/{uuid4()}/tracking-events")

    assert response.status_code == 200
    assert response.json() == []
