from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

from fastapi.testclient import TestClient

from erp_api.main import app
from erp_api.routers import tiktok as tiktok_router

client = TestClient(app)


def test_tiktok_callback_is_not_acknowledged_before_implementation() -> None:
    response = client.get("/api/v1/shops/tiktok/callback")

    assert response.status_code == 501


def test_tiktok_webhook_refuses_requests_when_secure_processing_is_unconfigured() -> (
    None
):
    response = client.post("/api/v1/webhooks/tiktok", content=b"{}")

    assert response.status_code == 503


class FakeWebhookService:
    def verify(self, body: bytes, signature: str, timestamp: str) -> None:
        return None

    async def store(self, payload: dict[str, object], body: bytes):
        return uuid4(), True, uuid4(), uuid4()


def test_tiktok_webhook_rejects_non_object_json_as_bad_request(monkeypatch) -> None:
    monkeypatch.setattr(
        app.state, "webhook_service", FakeWebhookService(), raising=False
    )

    response = client.post("/api/v1/webhooks/tiktok", json=[])

    assert response.status_code == 400


def test_tiktok_webhook_logs_enqueue_failures(monkeypatch) -> None:
    async def failing_create_pool(*args, **kwargs):
        raise RuntimeError("queue unavailable")

    monkeypatch.setattr(
        app.state, "webhook_service", FakeWebhookService(), raising=False
    )
    monkeypatch.setattr(
        app.state,
        "settings",
        SimpleNamespace(redis_url="redis://localhost:6379/0"),
        raising=False,
    )
    monkeypatch.setattr(tiktok_router, "create_pool", failing_create_pool)
    log_exception = Mock()
    monkeypatch.setattr(tiktok_router.logger, "exception", log_exception)

    response = client.post("/api/v1/webhooks/tiktok", json={"event": "order.updated"})

    assert response.status_code == 202
    assert response.json()["queued"] is False
    log_exception.assert_called_once()
    assert log_exception.call_args.args[0] == "webhook_enqueue_failed"
