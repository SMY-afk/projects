from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any


def _money(data: Mapping[str, Any], *keys: str) -> int:
    raw = next((data[key] for key in keys if key in data and data[key] is not None), 0)
    if isinstance(raw, Mapping):
        raw = raw.get("amount", raw.get("value", 0))
    try:
        return int(
            (Decimal(str(raw)) * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP)
        )
    except (InvalidOperation, ValueError, TypeError):
        return 0


def _timestamp(value: Any) -> datetime | None:
    number = _integer(value)
    return datetime.fromtimestamp(number, tz=UTC) if number else None


def _integer(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _text(data: Mapping[str, Any], *keys: str) -> str | None:
    return next(
        (
            _optional_text(data.get(key))
            for key in keys
            if _optional_text(data.get(key))
        ),
        None,
    )


def _optional_text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _optional_bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


