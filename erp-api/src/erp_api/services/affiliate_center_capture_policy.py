from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

AFFILIATE_CENTER_RAW_PAYLOAD_TTL_DAYS = 7
CAPTURE_EXECUTION_BOUNDARY = "current_browser_session_only"

CAPTURE_LOG_FIELD_ALLOWLIST = frozenset(
    {
        "context_count",
        "duplicates",
        "event",
        "expected_total",
        "pages_fetched",
        "page_count",
        "persisted_count",
        "fetched_count",
        "records_received",
        "records_unique",
        "request_id",
        "run_id",
        "shop_id",
        "tenant_id",
    }
)

CAPTURE_FORBIDDEN_FIELDS = frozenset(
    {
        "access_token",
        "address",
        "authorization",
        "buyer",
        "chat",
        "conversation",
        "cookie",
        "csrf_token",
        "email",
        "headers",
        "message",
        "oauth_code",
        "oauth_state",
        "password",
        "phone",
        "recipient",
        "refresh_token",
        "request_body",
        "request_headers",
        "response_headers",
        "session_id",
        "set_cookie",
        "sign",
        "signature",
        "shop_cipher",
        "token",
        "ms_token",
        "query_string",
        "raw_query",
        "request_query",
        "request_url",
        "x_tts_access_token",
    }
)
_NORMALIZED_FORBIDDEN_FIELDS = frozenset(
    re.sub(r"[^a-z0-9]", "", key.casefold()) for key in CAPTURE_FORBIDDEN_FIELDS
)


class CapturePolicyError(ValueError):
    pass


@dataclass(frozen=True)
class CaptureCompleteness:
    complete: bool
    terminal: bool
    reason: str
    uniqueRecordCount: int
    totalCount: int | None


def evaluate_capture_completeness(
    *,
    has_more: bool | None,
    next_cursor: str | None,
    unique_record_count: int,
    total_count: int | None,
) -> CaptureCompleteness:
    _non_negative_integer(unique_record_count, "unique_record_count")
    if total_count is not None:
        _non_negative_integer(total_count, "total_count")
    if has_more is not None and not isinstance(has_more, bool):
        raise CapturePolicyError("has_more must be boolean or null.")
    if next_cursor is not None and not isinstance(next_cursor, str):
        raise CapturePolicyError("next_cursor must be a string or null.")

    cursor_present = bool((next_cursor or "").strip())
    terminal = has_more is False or not cursor_present
    if has_more is True and not cursor_present:
        reason = "cursor_interrupted"
    elif not terminal:
        reason = "pagination_not_terminal"
    elif total_count is not None and unique_record_count != total_count:
        reason = "total_count_mismatch"
    else:
        reason = "complete"
    return CaptureCompleteness(
        complete=reason == "complete",
        terminal=terminal,
        reason=reason,
        uniqueRecordCount=unique_record_count,
        totalCount=total_count,
    )


def sanitize_capture_payload(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            key: sanitize_capture_payload(item)
            for key, item in value.items()
            if _payload_key_allowed(key)
        }
    if isinstance(value, (list, tuple)):
        return [sanitize_capture_payload(item) for item in value]
    if isinstance(value, str):
        return _sanitize_string(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    raise CapturePolicyError("Capture payload must contain JSON-compatible values.")


def validate_capture_log_fields(fields: Mapping[str, object]) -> dict[str, object]:
    unexpected = set(fields) - CAPTURE_LOG_FIELD_ALLOWLIST
    if unexpected:
        raise CapturePolicyError(
            "Capture log fields must use the strict allowlist: "
            + ", ".join(sorted(unexpected))
        )
    result: dict[str, object] = {}
    for key, value in fields.items():
        if value is not None and not isinstance(value, (str, bool, int, float)):
            raise CapturePolicyError(f"Capture log field {key} must be scalar.")
        if isinstance(value, str) and len(value) > 200:
            raise CapturePolicyError(f"Capture log field {key} is too long.")
        result[key] = value
    return result


def affiliate_center_capture_policy_contract() -> dict[str, object]:
    return {
        "executionBoundary": CAPTURE_EXECUTION_BOUNDARY,
        "browserCredentialTransfer": "prohibited",
        "backendHandoff": "sanitized_business_response_only",
        "triggerOwnership": {
            "pageCapture": {
                "owner": "capture_daemon",
                "trigger": "queued_sync_intent",
                "apiOrArqCanForce": False,
            },
            "officialApi": {
                "owner": "arq",
                "triggers": ["scheduled", "manual"],
            },
        },
        "rawResponseTtlDays": AFFILIATE_CENTER_RAW_PAYLOAD_TTL_DAYS,
        "logFieldAllowlist": sorted(CAPTURE_LOG_FIELD_ALLOWLIST),
        "forbiddenFields": sorted(CAPTURE_FORBIDDEN_FIELDS),
        "completeness": {
            "terminalRule": "has_more_false_or_next_cursor_empty",
            "countRule": "unique_record_count_equals_total_count_when_present",
            "mismatchStatus": "partial",
        },
    }


def _payload_key_allowed(key: object) -> bool:
    if not isinstance(key, str) or not key:
        raise CapturePolicyError("Capture payload keys must be non-empty strings.")
    normalized = re.sub(r"[^a-z0-9]", "", key.casefold())
    return normalized not in _NORMALIZED_FORBIDDEN_FIELDS


def _sanitize_string(value: str) -> str:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return value
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.netloc:
        return value
    if not parsed.query and not parsed.fragment:
        return value
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _non_negative_integer(value: object, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CapturePolicyError(f"{field} must be a non-negative integer.")
