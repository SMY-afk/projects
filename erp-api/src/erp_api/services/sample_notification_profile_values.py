from __future__ import annotations

import re
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation


def distribution_summary(
    value: object, *, limit: int, fixed_decimals: int | None = None
) -> str | None:
    if not isinstance(value, list):
        return None
    parts = []
    for raw in value:
        item = mapping(raw)
        label = text(item.get("label"))
        share = (
            _fixed_percentage_bps(item.get("share_bps"), fixed_decimals)
            if fixed_decimals is not None
            else percentage_bps(item.get("share_bps"))
        )
        if label and share != "—":
            parts.append(f"{label} {share}")
        if len(parts) == limit:
            break
    return " · ".join(parts) or None


def _fixed_percentage_bps(value: object, decimals: int) -> str:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not 0 <= value <= 10_000
        or not 0 <= decimals <= 2
    ):
        return "—"
    return f"{Decimal(value) / 100:.{decimals}f}%"


def label_summary(value: object, *, limit: int) -> str | None:
    if not isinstance(value, list):
        return None
    labels = [
        label for raw in value if (label := text(mapping(raw).get("label"))) is not None
    ]
    return " · ".join(labels[:limit]) or None


def money(value: object, currency: str | None) -> str:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        return "—"
    amount = Decimal(value) / 100
    symbol = {"USD": "$", "CNY": "¥", "EUR": "€", "GBP": "£"}.get(
        (currency or "").upper(), f"{(currency or '').upper()} " if currency else ""
    )
    return f"{symbol}{decimal_text(amount)}"


def percentage_bps(value: object) -> str:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or not 0 <= value <= 10_000
    ):
        return "—"
    return f"{decimal_text(Decimal(value) / 100)}%"


def integer_text(value: object) -> str:
    return (
        f"{value:,}"
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0
        else "—"
    )


def out_of_five(value: Decimal | None) -> str:
    return (
        f"{decimal_text(value)}/5"
        if value is not None and value.is_finite() and 0 <= value <= 5
        else "—"
    )


def score(value: object) -> str:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return "—"
    return decimal_text(parsed) if parsed.is_finite() and 0 <= parsed <= 100 else "—"


def date_text(value: object) -> str | None:
    value_text = text(value)
    if value_text and re.fullmatch(r"\d{4}-\d{2}-\d{2}.*", value_text):
        return value_text[:10]
    return None


def mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def decimal_text(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.01")), "f").rstrip("0").rstrip(".")
