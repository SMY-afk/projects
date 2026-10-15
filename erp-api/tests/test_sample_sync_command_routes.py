from __future__ import annotations

from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from erp_api.core.permissions import AFFILIATE_CENTER_VIEW, SYNC_TRIGGER
from erp_api.routers import sample_applications
from erp_api.routers.auth import get_authenticated_user, require_session
from erp_api.services.auth import AuthSession, CurrentUser
from erp_api.services.sample_sync_command import (
    SampleSyncCommandService,
    SampleSyncPlan,
    SampleSyncTarget,
    _readiness,
)


class FakeCommandService:
    def __init__(self, plan: SampleSyncPlan | None) -> None:
        self.result = plan
        self.plan_calls = []
        self.enqueue_calls = []

    async def plan(self, tenant_id, shop_id, **options):
        self.plan_calls.append((tenant_id, shop_id, options))
        return self.result

    async def enqueue(self, queue, plan):
        self.enqueue_calls.append((queue, plan))
        return "safe-job-id"


def _plan(*, ready: bool = True, reason_code: str = "ready") -> SampleSyncPlan:
    return SampleSyncPlan(
        tenant_id=uuid4(),
        shop_id=uuid4(),
        shop_name="Test Shop",
        source_type="official_api",
        mode="active",
        ready=ready,
        reason_code=reason_code,
    )


def _client(
    permissions: list[str], plan: SampleSyncPlan | None
) -> tuple[TestClient, FakeCommandService, object]:
    service = FakeCommandService(plan)
    queue = object()
    app = FastAPI()
    app.include_router(sample_applications.router, prefix="/api")
    app.state.arq_queue = queue
    user_id = uuid4()
    tenant_id = plan.tenant_id if plan is not None else uuid4()
    app.dependency_overrides[require_session] = lambda: AuthSession(user_id, tenant_id)
    app.dependency_overrides[get_authenticated_user] = lambda: CurrentUser(
        user_id, "Admin", "admin", [], permissions
    )
    app.dependency_overrides[sample_applications._command_service] = lambda: service
    return TestClient(app), service, queue


def _payload(plan: SampleSyncPlan) -> dict[str, str]:
    return {
        "shopId": str(plan.shop_id),
        "sourceType": plan.source_type,
        "mode": plan.mode,
    }


def test_dry_run_checks_only_the_session_tenant_and_does_not_enqueue() -> None:
    plan = _plan()
    client, service, _queue = _client([AFFILIATE_CENTER_VIEW], plan)

    response = client.post(
        "/api/sample-applications/sync/dry-run",
        json=_payload(plan),
    )

    assert response.status_code == 200
    assert response.json() == {
        "shopId": str(plan.shop_id),
        "shopName": "Test Shop",
        "sourceType": "official_api",
        "mode": "active",
        "dryRun": True,
        "ready": True,
        "reasonCode": "ready",
    }
    assert service.plan_calls[0][0] == plan.tenant_id
    assert service.enqueue_calls == []


def test_dry_run_requires_view_but_not_sync_permission() -> None:
    plan = _plan()
    assert _client([], plan)[0].post(
        "/api/sample-applications/sync/dry-run", json=_payload(plan)
    ).status_code == 403
    assert _client([AFFILIATE_CENTER_VIEW], plan)[0].post(
        "/api/sample-applications/sync/dry-run", json=_payload(plan)
    ).status_code == 200


def test_single_shop_sync_requires_trigger_permission_and_uses_queue() -> None:
    plan = _plan()
    assert _client([AFFILIATE_CENTER_VIEW], plan)[0].post(
        "/api/sample-applications/sync", json=_payload(plan)
    ).status_code == 403

    client, service, queue = _client(
        [AFFILIATE_CENTER_VIEW, SYNC_TRIGGER], plan
    )
    response = client.post("/api/sample-applications/sync", json=_payload(plan))

    assert response.status_code == 202
    assert response.json()["jobId"] == "safe-job-id"
    assert response.json()["status"] == "queued"
    assert service.enqueue_calls == [(queue, plan)]


def test_single_shop_sync_rejects_blocked_plan_without_queueing() -> None:
    plan = _plan(ready=False, reason_code="missing_sample_scope")
    client, service, _queue = _client(
        [AFFILIATE_CENTER_VIEW, SYNC_TRIGGER], plan
    )

    response = client.post("/api/sample-applications/sync", json=_payload(plan))

    assert response.status_code == 409
    assert response.json()["detail"] == {"code": "missing_sample_scope"}
    assert service.enqueue_calls == []


def test_sync_request_forbids_all_shop_and_tenant_overrides() -> None:
    plan = _plan()
    client, _service, _queue = _client(
        [AFFILIATE_CENTER_VIEW, SYNC_TRIGGER], plan
    )
    payload = {**_payload(plan), "allShops": True, "tenantId": str(uuid4())}

    response = client.post("/api/sample-applications/sync", json=payload)

    assert response.status_code == 422


def test_missing_or_cross_tenant_shop_is_hidden_as_not_found() -> None:
    plan = _plan()
    client, service, _queue = _client([AFFILIATE_CENTER_VIEW], None)

    response = client.post(
        "/api/sample-applications/sync/dry-run", json=_payload(plan)
    )

    assert response.status_code == 404
    assert service.enqueue_calls == []


def test_readiness_reports_safe_reason_codes() -> None:
    base = {
        "shop_id": uuid4(),
        "shop_name": "Test Shop",
        "auth_status": "authorized",
        "has_access_token": True,
        "has_shop_cipher": True,
        "scopes": ("seller.affiliate_collaboration.read",),
    }

    assert _readiness(SampleSyncTarget(**base), "official_api") == (True, "ready")
    assert _readiness(SampleSyncTarget(**base), "hubstudio_cdp") == (
        False,
        "hubstudio_listener_required",
    )
    assert _readiness(
        SampleSyncTarget(**{**base, "scopes": ()}), "official_api"
    ) == (False, "missing_sample_scope")


def test_command_service_targets_the_dedicated_sample_queue() -> None:
    plan = _plan()

    class Queue:
        def __init__(self) -> None:
            self.call = None

        async def enqueue_job(self, *args, **kwargs):
            self.call = (args, kwargs)
            return object()

    queue = Queue()
    service = SampleSyncCommandService(database=None)

    import asyncio

    job_id = asyncio.run(service.enqueue(queue, plan))

    args, kwargs = queue.call
    assert args[0] == "sync_sample_applications_job"
    assert args[1:4] == (str(plan.tenant_id), str(plan.shop_id), "active")
    assert kwargs["_queue_name"] == "arq:sample"
    assert kwargs["_job_id"] == job_id
