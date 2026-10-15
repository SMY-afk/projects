from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from erp_api.services.tiktok_transport import TikTokApiError

SAFE_RESOURCE_ID = re.compile(r"^[A-Za-z0-9_-]+$")


def invalid(message: str) -> TikTokApiError:
    return TikTokApiError(
        message,
        code="invalid_finance_response",
        status_code=502,
    )


def data_object(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        raise invalid("TikTok Finance response was not an object.")
    data = payload.get("data")
    if not isinstance(data, Mapping):
        raise invalid("TikTok Finance response did not contain a data object.")
    return data


def object_value(data: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = data.get(key)
    if not isinstance(value, Mapping):
        raise invalid(f"TikTok Finance field {key} was not an object.")
    return value


def list_value(data: Mapping[str, Any], key: str) -> list[Any]:
    value = data.get(key)
    if not isinstance(value, list):
        raise invalid(f"TikTok Finance field {key} was not a list.")
    return value


def required_text(data: Mapping[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise invalid(f"TikTok Finance field {key} was not a non-empty string.")
    return value


def optional_text(data: Mapping[str, Any], key: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise invalid(f"TikTok Finance field {key} was not null or a string.")
    return value or None


def currency(data: Mapping[str, Any], key: str = "currency") -> str:
    value = required_text(data, key)
    if len(value) != 3 or not value.isascii() or not value.isalpha():
        raise invalid(f"TikTok Finance field {key} was not an ISO currency.")
    if value != value.upper():
        raise invalid(f"TikTok Finance field {key} was not uppercase.")
    return value


def money(data: Mapping[str, Any], key: str) -> Decimal:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise invalid(f"TikTok Finance field {key} was not a decimal string.")
    try:
        parsed = Decimal(value)
    except InvalidOperation as error:
        raise invalid(f"TikTok Finance field {key} was not a valid decimal.") from error
    if not parsed.is_finite():
        raise invalid(f"TikTok Finance field {key} was not finite.")
    return parsed


def count(data: Mapping[str, Any], key: str = "total_count") -> int:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise invalid(f"TikTok Finance field {key} was not a non-negative integer.")
    return value


def timestamp(data: Mapping[str, Any], key: str) -> datetime:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise invalid(f"TikTok Finance field {key} was not a positive Unix timestamp.")
    try:
        return datetime.fromtimestamp(value, tz=UTC)
    except (OverflowError, OSError, ValueError) as error:
        raise invalid(
            f"TikTok Finance field {key} was outside the timestamp range."
        ) from error


def optional_timestamp(data: Mapping[str, Any], key: str) -> datetime | None:
    value = data.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise invalid(f"TikTok Finance field {key} was not a Unix timestamp.")
    if value == 0:
        return None
    return timestamp(data, key)


def breakdown(data: Mapping[str, Any], key: str) -> dict[str, Decimal]:
    raw = object_value(data, key)
    flattened: dict[str, Decimal] = {}
    _flatten_breakdown(raw, flattened, prefix="")
    return flattened


def _flatten_breakdown(
    raw: Mapping[str, Any], target: dict[str, Decimal], *, prefix: str
) -> None:
    for raw_key, value in raw.items():
        if not isinstance(raw_key, str) or not raw_key:
            raise invalid("TikTok Finance breakdown contained an invalid key.")
        path = f"{prefix}.{raw_key}" if prefix else raw_key
        if isinstance(value, Mapping):
            _flatten_breakdown(value, target, prefix=path)
            continue
        target[path] = money({path: value}, path)


def validate_resource_id(value: str, field: str) -> None:
    if not isinstance(value, str) or not SAFE_RESOURCE_ID.fullmatch(value):
        raise ValueError(f"{field} contains unsafe characters.")
