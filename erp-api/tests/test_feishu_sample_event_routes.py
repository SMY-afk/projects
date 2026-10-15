import base64
import hashlib
import json

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from fastapi.testclient import TestClient
from pydantic import SecretStr

import erp_api.main as main_module
from erp_api.main import app
from erp_api.services.feishu_sample_event_processor import (
    FeishuBusinessEventProcessor,
    FeishuSampleEventProcessResult,
)
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


def test_configured_app_attaches_event_processor_for_all_sample_tables(monkeypatch) -> None:
    settings = app.state.settings.model_copy(
        update={
            "feishu_app_id": "cli_test_app",
            "feishu_app_secret": SecretStr("app-secret"),
            "feishu_sample_base_token": SecretStr("base-token"),
            "feishu_sample_table_id": "default-table",
            "feishu_sample_shop_table_ids": {"shop-1": "shop-table"},
            "feishu_bd_assignment_record_table_id": "assignment-table",
            "feishu_event_verification_token": SecretStr("verification-token"),
            "feishu_event_encrypt_key": SecretStr("encrypt-key"),
        }
    )
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)

    configured_app = main_module.create_app()

    processor = configured_app.state.feishu_sample_event_processor
    assert isinstance(processor, FeishuBusinessEventProcessor)
    assert set(processor._sample_processors) == {"default-table", "shop-table"}


def _event_payload(
    *,
    record_id: str = "rec-1",
    changed_field_ids: tuple[str, ...] = ("fld-bd",),
    **header_overrides,
):
    header = {
        "event_id": "event-1",
        "event_type": "drive.file.bitable_record_changed_v1",
        "token": "verification-token",
        "app_id": "cli_test_app",
        "create_time": str(TEST_NOW * 1000),
    }
    header.update(header_overrides)
    return {
        "schema": "2.0",
        "header": header,
        "event": {
            "file_type": "bitable",
            "file_token": "base-token",
            "table_id": "table-id",
            "operator_id": {"open_id": "ou-user"},
            "action_list": [
                {
                    "action": "record_edited",
                    "record_id": record_id,
                    "after_value": [
                        {"field_id": field_id, "field_value": "value"}
                        for field_id in changed_field_ids
                    ],
                }
            ],
        },
    }


def _body(payload: object) -> bytes:
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()


def _encrypted(payload: object) -> dict[str, str]:
    iv = b"0123456789abcdef"
    key = hashlib.sha256(ENCRYPT_KEY.encode()).digest()
    padder = padding.PKCS7(128).padder()
    content = padder.update(_body(payload)) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    return {"encrypt": base64.b64encode(iv + encryptor.update(content) + encryptor.finalize()).decode()}


def _signed_headers(
    body: bytes,
    *,
    timestamp: int = TEST_NOW,
    nonce: str = "nonce-1",
    encrypt_key: str = ENCRYPT_KEY,
) -> dict[str, str]:
    prefix = f"{timestamp}{nonce}{encrypt_key}".encode()
    return {
        "content-type": "application/json",
        "X-Lark-Request-Timestamp": str(timestamp),
        "X-Lark-Request-Nonce": nonce,
        "X-Lark-Signature": hashlib.sha256(prefix + body).hexdigest(),
    }


def _post_signed(payload: object, **signature_options):
    body = _body(payload)
    return client.post(
        CALLBACK_PATH,
        content=body,
        headers=_signed_headers(body, **signature_options),
    )


def test_feishu_callback_refuses_requests_when_unconfigured(monkeypatch) -> None:
    monkeypatch.setattr(app.state, "feishu_sample_event_receiver", None, raising=False)

    response = client.post(CALLBACK_PATH, content=_body({"type": "url_verification"}))

    assert response.status_code == 503


def test_feishu_callback_returns_verified_url_challenge(monkeypatch) -> None:
    monkeypatch.setattr(
        app.state, "feishu_sample_event_receiver", _receiver(), raising=False
    )

    response = client.post(
        CALLBACK_PATH,
        content=_body(
            {
                "type": "url_verification",
                "token": "verification-token",
                "challenge": "challenge-1",
            }
        ),
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 200
    assert response.json() == {"challenge": "challenge-1"}


def test_feishu_callback_rejects_url_challenge_with_wrong_token(monkeypatch) -> None:
    monkeypatch.setattr(
        app.state, "feishu_sample_event_receiver", _receiver(), raising=False
    )

    response = client.post(
        CALLBACK_PATH,
        content=_body(
            {
                "type": "url_verification",
                "token": "wrong-token",
                "challenge": "challenge-1",
            }
        ),
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 401


def test_feishu_callback_retries_v2_event_until_processing_is_configured(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        app.state, "feishu_sample_event_receiver", _receiver(), raising=False
    )
    monkeypatch.setattr(app.state, "feishu_sample_event_processor", None, raising=False)

    response = _post_signed(_event_payload())

    assert response.status_code == 503
    assert response.headers["retry-after"] == "60"


def test_feishu_callback_processes_verified_record_event(monkeypatch) -> None:
    class FakeProcessor:
        def __init__(self) -> None:
            self.receipts = []

        async def process(self, receipt):
            self.receipts.append(receipt)
            return FeishuSampleEventProcessResult(
                applied_count=1,
                duplicate_count=0,
                unchanged_count=0,
                ignored_count=0,
            )

    processor = FakeProcessor()
    monkeypatch.setattr(
        app.state, "feishu_sample_event_receiver", _receiver(), raising=False
    )
    monkeypatch.setattr(
        app.state, "feishu_sample_event_processor", processor, raising=False
    )

    response = _post_signed(_event_payload())

    assert response.status_code == 200
    assert response.json() == {
        "code": 0,
        "applied": 1,
        "duplicate": 0,
        "unchanged": 0,
        "ignored": 0,
    }
    assert processor.receipts[0].record_edits[0].record_id == "rec-1"


def test_feishu_callback_reports_unknown_record_without_acknowledging_it(
    monkeypatch,
) -> None:
    class MissingRecordProcessor:
        async def process(self, receipt):
            raise LookupError(receipt.event_id)

    monkeypatch.setattr(
        app.state, "feishu_sample_event_receiver", _receiver(), raising=False
    )
    monkeypatch.setattr(
        app.state,
        "feishu_sample_event_processor",
        MissingRecordProcessor(),
        raising=False,
    )

    response = _post_signed(_event_payload(record_id="rec-unknown"))

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"
    assert response.json()["message"] == "Resource not found."


def test_feishu_callback_rejects_missing_or_wrong_signature(monkeypatch) -> None:
    monkeypatch.setattr(
        app.state, "feishu_sample_event_receiver", _receiver(), raising=False
    )
    body = _body(_event_payload())

    missing = client.post(CALLBACK_PATH, content=body)
    wrong_headers = _signed_headers(body)
    wrong_headers["X-Lark-Signature"] = "0" * 64
    wrong = client.post(CALLBACK_PATH, content=body, headers=wrong_headers)

    assert missing.status_code == 401
    assert wrong.status_code == 401


def test_feishu_callback_signature_covers_exact_raw_body(monkeypatch) -> None:
    monkeypatch.setattr(
        app.state, "feishu_sample_event_receiver", _receiver(), raising=False
    )
    body = _body(_event_payload())

    response = client.post(
        CALLBACK_PATH,
        content=b" " + body,
        headers=_signed_headers(body),
    )

    assert response.status_code == 401


def test_feishu_callback_rejects_stale_or_future_timestamp(monkeypatch) -> None:
    monkeypatch.setattr(
        app.state, "feishu_sample_event_receiver", _receiver(), raising=False
    )

    stale = _post_signed(_event_payload(), timestamp=TEST_NOW - 301)
    future = _post_signed(_event_payload(), timestamp=TEST_NOW + 301)

    assert stale.status_code == 401
    assert future.status_code == 401


def test_feishu_callback_rejects_wrong_token_without_disclosing_secrets(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        app.state, "feishu_sample_event_receiver", _receiver(), raising=False
    )

    response = _post_signed(_event_payload(token="wrong-token"))

    assert response.status_code == 401
    rendered = response.text
    assert "verification-token" not in rendered
    assert "wrong-token" not in rendered
    assert ENCRYPT_KEY not in rendered


def test_feishu_callback_rejects_wrong_app_and_invalid_encrypted_payload(monkeypatch) -> None:
    monkeypatch.setattr(
        app.state, "feishu_sample_event_receiver", _receiver(), raising=False
    )

    wrong_app = _post_signed(_event_payload(app_id="cli_wrong"))
    encrypted = _post_signed({"encrypt": "ciphertext"})

    assert wrong_app.status_code == 401
    assert encrypted.status_code == 400


def test_feishu_callback_processes_encrypted_record_event(monkeypatch) -> None:
    class FakeProcessor:
        async def process(self, receipt):
            assert receipt.table_id == "table-id"
            assert receipt.record_edits[0].record_id == "rec-1"
            return FeishuSampleEventProcessResult(applied_count=1)

    monkeypatch.setattr(app.state, "feishu_sample_event_receiver", _receiver(), raising=False)
    monkeypatch.setattr(app.state, "feishu_sample_event_processor", FakeProcessor(), raising=False)

    response = _post_signed(_encrypted(_event_payload()))

    assert response.status_code == 200
    assert response.json()["applied"] == 1


def test_feishu_callback_rejects_event_id_too_long_for_idempotency_key(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        app.state, "feishu_sample_event_receiver", _receiver(), raising=False
    )

    response = _post_signed(_event_payload(event_id="x" * 256))

    assert response.status_code == 400
