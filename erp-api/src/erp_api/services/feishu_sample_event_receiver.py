from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

DEFAULT_MAX_EVENT_AGE_SECONDS = 300
BITABLE_RECORD_CHANGED_EVENT = "drive.file.bitable_record_changed_v1"


class FeishuEventAuthenticationError(RuntimeError):
    pass


class FeishuEventPayloadError(RuntimeError):
    pass


@dataclass(frozen=True)
class FeishuRecordEdit:
    record_id: str
    changed_field_ids: frozenset[str]


@dataclass(frozen=True)
class FeishuEventReceipt:
    kind: Literal["challenge", "event"]
    challenge: str | None = None
    event_id: str | None = None
    event_type: str | None = None
    occurred_at: datetime | None = None
    file_token: str | None = None
    table_id: str | None = None
    operator_id: str | None = None
    record_edits: tuple[FeishuRecordEdit, ...] = ()


class FeishuSampleEventReceiver:
    """Validate the basic Feishu callback envelope without applying business data."""

    def __init__(
        self,
        *,
        verification_token: str,
        encrypt_key: str,
        app_id: str,
        clock: Callable[[], float] = time.time,
        max_age_seconds: int = DEFAULT_MAX_EVENT_AGE_SECONDS,
    ) -> None:
        if not verification_token or not encrypt_key or not app_id:
            raise ValueError("Feishu event receiver configuration is incomplete.")
        if max_age_seconds <= 0:
            raise ValueError("Feishu event max age must be positive.")
        self._verification_token = verification_token
        self._encrypt_key = encrypt_key
        self._app_id = app_id
        self._clock = clock
        self._max_age_seconds = max_age_seconds

    def verify_request(
        self,
        body: bytes,
        *,
        timestamp: str | None,
        nonce: str | None,
        signature: str | None,
    ) -> None:
        if (
            not timestamp
            or not timestamp.isdecimal()
            or len(timestamp) > 16
            or not nonce
            or len(nonce) > 256
            or not signature
            or len(signature) != 64
            or any(character not in "0123456789abcdefABCDEF" for character in signature)
        ):
            raise FeishuEventAuthenticationError(
                "Feishu callback security headers are invalid."
            )
        sent_at = int(timestamp)
        if abs(self._clock() - sent_at) > self._max_age_seconds:
            raise FeishuEventAuthenticationError(
                "Feishu callback timestamp is outside the accepted window."
            )
        prefix = f"{timestamp}{nonce}{self._encrypt_key}".encode()
        expected = hashlib.sha256(prefix + body).hexdigest()
        if not hmac.compare_digest(expected, signature.casefold()):
            raise FeishuEventAuthenticationError(
                "Feishu callback signature is invalid."
            )

    def receive(self, payload: dict[str, Any]) -> FeishuEventReceipt:
        if "encrypt" in payload:
            payload = self._decrypt_payload(payload["encrypt"])
        if payload.get("type") == "url_verification":
            self._verify_token(payload.get("token"))
            challenge = _required_identifier(payload.get("challenge"), "challenge")
            return FeishuEventReceipt(kind="challenge", challenge=challenge)
        if payload.get("schema") != "2.0":
            raise FeishuEventPayloadError("Feishu callback schema is unsupported.")
        header = payload.get("header")
        event = payload.get("event")
        if not isinstance(header, dict) or not isinstance(event, dict):
            raise FeishuEventPayloadError("Feishu callback envelope is invalid.")
        self._verify_token(header.get("token"))
        if not hmac.compare_digest(str(header.get("app_id") or ""), self._app_id):
            raise FeishuEventAuthenticationError("Feishu callback app is invalid.")
        event_type = _required_identifier(header.get("event_type"), "event_type")
        if event_type != BITABLE_RECORD_CHANGED_EVENT:
            raise FeishuEventPayloadError("Feishu callback event type is unsupported.")
        operator = event.get("operator_id")
        if not isinstance(operator, dict):
            raise FeishuEventPayloadError("Feishu callback operator is invalid.")
        if event.get("file_type") != "bitable":
            raise FeishuEventPayloadError("Feishu callback file type is invalid.")
        return FeishuEventReceipt(
            kind="event",
            event_id=_required_identifier(
                header.get("event_id"), "event_id", max_length=255
            ),
            event_type=event_type,
            occurred_at=_event_time(header.get("create_time")),
            file_token=_required_identifier(
                event.get("file_token"), "file_token", max_length=255
            ),
            table_id=_required_identifier(
                event.get("table_id"), "table_id", max_length=128
            ),
            operator_id=_required_identifier(
                operator.get("open_id"), "operator_id", max_length=255
            ),
            record_edits=_record_edits(event.get("action_list")),
        )

    def _decrypt_payload(self, encrypted: object) -> dict[str, Any]:
        if not isinstance(encrypted, str) or not encrypted:
            raise FeishuEventPayloadError("Feishu callback ciphertext is invalid.")
        try:
            data = base64.b64decode(encrypted, validate=True)
            if len(data) < 32 or (len(data) - 16) % 16:
                raise ValueError("Invalid ciphertext length")
            key = hashlib.sha256(self._encrypt_key.encode()).digest()
            decryptor = Cipher(
                algorithms.AES(key), modes.CBC(data[:16])
            ).decryptor()
            padded = decryptor.update(data[16:]) + decryptor.finalize()
            unpadder = padding.PKCS7(128).unpadder()
            plain = unpadder.update(padded) + unpadder.finalize()
            payload = json.loads(plain)
        except (binascii.Error, ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise FeishuEventPayloadError("Feishu callback ciphertext is invalid.") from error
        if not isinstance(payload, dict):
            raise FeishuEventPayloadError("Feishu callback payload is invalid.")
        return payload

    def _verify_token(self, candidate: object) -> None:
        if not isinstance(candidate, str) or not hmac.compare_digest(
            candidate, self._verification_token
        ):
            raise FeishuEventAuthenticationError(
                "Feishu callback verification token is invalid."
            )


def _required_identifier(value: object, name: str, *, max_length: int = 256) -> str:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= max_length
        or any(character.isspace() for character in value)
    ):
        raise FeishuEventPayloadError(f"Feishu callback {name} is invalid.")
    return value


def _event_time(value: object) -> datetime:
    if not isinstance(value, str) or not value.isdecimal() or len(value) > 16:
        raise FeishuEventPayloadError("Feishu callback create_time is invalid.")
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=UTC)
    except (OverflowError, OSError, ValueError) as error:
        raise FeishuEventPayloadError(
            "Feishu callback create_time is invalid."
        ) from error


def _record_edits(value: object) -> tuple[FeishuRecordEdit, ...]:
    if not isinstance(value, list):
        raise FeishuEventPayloadError("Feishu callback action_list is invalid.")
    by_record: dict[str, set[str]] = {}
    for action in value:
        if not isinstance(action, dict):
            raise FeishuEventPayloadError("Feishu callback action is invalid.")
        action_type = action.get("action")
        if action_type in {"record_added", "record_deleted"}:
            continue
        if action_type != "record_edited":
            raise FeishuEventPayloadError("Feishu callback action is unsupported.")
        record_id = _required_identifier(
            action.get("record_id"), "record_id", max_length=128
        )
        after_values = action.get("after_value")
        if not isinstance(after_values, list) or not after_values:
            raise FeishuEventPayloadError("Feishu callback after_value is invalid.")
        field_ids = by_record.setdefault(record_id, set())
        for field_value in after_values:
            if not isinstance(field_value, dict):
                raise FeishuEventPayloadError(
                    "Feishu callback field change is invalid."
                )
            field_ids.add(
                _required_identifier(
                    field_value.get("field_id"), "field_id", max_length=128
                )
            )
    return tuple(
        FeishuRecordEdit(record_id, frozenset(field_ids))
        for record_id, field_ids in by_record.items()
    )
