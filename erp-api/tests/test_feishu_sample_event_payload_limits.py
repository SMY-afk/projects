import hashlib

from fastapi.testclient import TestClient

from erp_api.main import app
from erp_api.routers.feishu_sample_events import MAX_FEISHU_EVENT_BYTES
from erp_api.services.feishu_sample_event_receiver import FeishuSampleEventReceiver

client = TestClient(app)
CALLBACK_PATH = "/api/v1/webhooks/feishu/sample-applications"
TEST_NOW = 1_800_000_000
ENCRYPT_KEY = "encrypt-key"


def _receiver() -> FeishuSampleEventReceiver:
    return FeishuSampleEventReceiver(
        verification_token="verification-token",
        encrypt_key=ENCRYPT_KEY,
        app_id="cli_test_app",
        clock=lambda: TEST_NOW,
    )


def _signed_headers(body: bytes) -> dict[str, str]:
    timestamp = str(TEST_NOW)
    nonce = "nonce-1"
    prefix = f"{timestamp}{nonce}{ENCRYPT_KEY}".encode()
    return {
        "content-type": "application/json",
        "X-Lark-Request-Timestamp": timestamp,
        "X-Lark-Request-Nonce": nonce,
        "X-Lark-Signature": hashlib.sha256(prefix + body).hexdigest(),
    }


def test_feishu_callback_rejects_invalid_and_oversized_payload(monkeypatch) -> None:
    monkeypatch.setattr(
        app.state, "feishu_sample_event_receiver", _receiver(), raising=False
    )
    invalid_body = b"not-json"

    invalid = client.post(
        CALLBACK_PATH,
        content=invalid_body,
        headers=_signed_headers(invalid_body),
    )
    oversized = client.post(
        CALLBACK_PATH,
        content=b"x" * (MAX_FEISHU_EVENT_BYTES + 1),
        headers={"content-type": "application/json"},
    )

    assert invalid.status_code == 400
    assert oversized.status_code == 413
