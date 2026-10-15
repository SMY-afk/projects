from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any


def text(value: object) -> str | None:
    return str(value).strip() if value not in (None, "") else None


def integer_text(value: object) -> int | None:
    normalized = text(value)
    try:
        return int(normalized.replace(",", "")) if normalized is not None else None
    except ValueError:
        return None


def money(value: object) -> dict[str, str]:
    normalized = (text(value) or "").replace("$", "").replace(",", "")
    return {"amount": normalized, "currency": "USD"}


def percentage(value: object) -> str | None:
    normalized = text(value)
    return normalized.removesuffix("%") if normalized is not None else None


def commission_rate(value: object) -> str | None:
    try:
        return str(Decimal(str(value)) / Decimal(10_000))
    except (InvalidOperation, TypeError):
        return None


def expiration_time(
    application: Mapping[str, Any], observed_at: datetime
) -> int | None:
    expires_in = application.get("expired_in")
    if not isinstance(expires_in, int) or expires_in <= 0:
        return None
    return int((observed_at + timedelta(milliseconds=expires_in)).timestamp())


def application_time(application: Mapping[str, Any]) -> int | None:
    created = integer_text(application.get("create_time"))
    return created // 1000 if created is not None and created > 0 else None
