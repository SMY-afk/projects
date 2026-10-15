from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any


def avatar_object_key(raw: object) -> str | None:
    value = text(raw)
    if (
        value
        and value.startswith("sample/creator-avatars/")
        and ".." not in value
        and "\\" not in value
        and len(value) <= 512
    ):
        return value
    return None


def source_hash(raw: object) -> str | None:
    value = text(raw)
    if value and re.fullmatch(r"[0-9a-fA-F]{64}", value):
        return value.casefold()
    return None


def money_minor(raw: object) -> int | None:
    value = raw.get("amount") if isinstance(raw, dict) else raw
    number = decimal(raw=value)
    if number is None or number < 0:
        return None
    return int((number * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def basis_points(raw: object) -> int | None:
    value = decimal(raw)
    if value is None or not 0 <= value <= 10_000:
        return None
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def distribution_basis_points(raw: object, *, ratio_key: bool) -> int | None:
    value = decimal(raw)
    if value is None or value < 0:
        return None
    if ratio_key and value <= 1:
        value *= 100
    if value > 100:
        return None
    return int((value * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def score_value(raw: object) -> str | None:
    value = decimal(raw)
    if value is None or not 0 <= value <= 100:
        return None
    return decimal_string(value)


def decimal(raw: object) -> Decimal | None:
    if raw in (None, "") or isinstance(raw, bool):
        return None
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, ValueError):
        return None
    return value if value.is_finite() else None


def decimal_string(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.01")), "f")


def integer(raw: object) -> int | None:
    if isinstance(raw, int) and not isinstance(raw, bool) and raw >= 0:
        return raw
    return None


def text(raw: object) -> str | None:
    if isinstance(raw, (str, int)) and (value := str(raw).strip()):
        return value
    return None


def text_list(raw: object) -> list[str] | None:
    if not isinstance(raw, list):
        return None
    values = [value for item in raw if (value := text(item))]
    return values or None


def mapping(raw: object) -> dict[str, Any]:
    return dict(raw) if isinstance(raw, dict) else {}


def first(values: dict[str, Any], keys: tuple[str, ...]) -> object:
    return next(
        (values[key] for key in keys if values.get(key) not in (None, "")), None
    )


def without_empty(values: dict[str, Any]) -> dict[str, Any] | None:
    result = {
        key: value for key, value in values.items() if value not in (None, [], {})
    }
    return result or None


def put(target: dict[str, object], key: str, value: object) -> None:
    if value not in (None, [], {}):
        target[key] = value
