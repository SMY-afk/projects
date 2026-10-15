from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from erp_api.services.tiktok_transport import TikTokApiError


@dataclass(frozen=True)
class TikTokReturnLine:
    platform_return_line_id: str
    platform_order_line_id: str
    seller_sku: str | None
    requested_quantity: int


@dataclass(frozen=True)
class TikTokReturn:
    platform_return_id: str
    platform_order_id: str
    request_type: str
    status: str
    platform_status: str
    reason_code: str
    reason_text: str | None
    created_at: datetime
    updated_at: datetime
    refund_currency: str | None
    refund_amount_minor: int | None
    lines: list[TikTokReturnLine]
    raw_payload: dict[str, object]


@dataclass(frozen=True)
class TikTokReturnPage:
    returns: list[TikTokReturn]
    next_page_token: str
    total_count: int | None


def parse_return_page_response(payload: Mapping[str, Any]) -> TikTokReturnPage:
    data = payload.get("data")
    if not isinstance(data, Mapping):
        raise _invalid("TikTok return response did not contain data.")
    rows = data.get("return_orders", [])
    if not isinstance(rows, list):
        raise _invalid("TikTok return response did not contain a return_orders list.")
    token = data.get("next_page_token", "")
    if not isinstance(token, str):
        raise _invalid("TikTok return response contained an invalid page token.")
    return TikTokReturnPage(
        returns=[_parse_return(row) for row in rows],
        next_page_token=token,
        total_count=_integer(data.get("total_count")),
    )


def _parse_return(value: Any) -> TikTokReturn:
    if not isinstance(value, Mapping):
        raise _invalid("TikTok return response contained an invalid record.")
    return_id = _text(value, "return_id")
    order_id = _text(value, "order_id")
    platform_status = _text(value, "return_status")
    created_at = _timestamp(value.get("create_time"))
    updated_at = _timestamp(value.get("update_time"))
    raw_lines = value.get("return_line_items", [])
    if not all((return_id, order_id, platform_status, created_at, updated_at)):
        raise _invalid("TikTok return missed an ID, status, or timestamp.")
    if not isinstance(raw_lines, list):
        raise _invalid("TikTok return contained invalid line items.")
    amount = value.get("refund_amount")
    money = amount if isinstance(amount, Mapping) else {}
    return TikTokReturn(
        platform_return_id=return_id,
        platform_order_id=order_id,
        request_type=_request_type(_text(value, "return_type")),
        status=_status(platform_status),
        platform_status=platform_status,
        reason_code=(_text(value, "return_reason") or "platform_unspecified")[:64],
        reason_text=_optional_text(value.get("return_reason_text")),
        created_at=created_at,
        updated_at=updated_at,
        refund_currency=(_text(money, "currency") or "")[:3] or None,
        refund_amount_minor=_money_minor(money.get("refund_total")),
        lines=[_parse_line(item) for item in raw_lines],
        raw_payload=dict(value),
    )


def _parse_line(value: Any) -> TikTokReturnLine:
    if not isinstance(value, Mapping):
        raise _invalid("TikTok return contained an invalid line item.")
    return_line_id = _text(value, "return_line_item_id")
    order_line_id = _text(value, "order_line_item_id")
    if not return_line_id or not order_line_id:
        raise _invalid("TikTok return line missed its platform identity.")
    return TikTokReturnLine(
        platform_return_line_id=return_line_id,
        platform_order_line_id=order_line_id,
        seller_sku=_text(value, "seller_sku"),
        requested_quantity=max(1, _integer(value.get("quantity")) or 1),
    )


def _request_type(value: str | None) -> str:
    normalized = (value or "").upper()
    if normalized == "REFUND":
        return "refund"
    if "EXCHANGE" in normalized or "REPLACEMENT" in normalized:
        return "exchange"
    return "return"


def _status(value: str) -> str:
    normalized = value.upper()
    if "CANCEL" in normalized:
        return "cancelled"
    if "REJECT" in normalized:
        return "rejected"
    if "COMPLETE" in normalized:
        return "approved"
    return "pending_review"


def _text(value: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        text = _optional_text(value.get(key))
        if text:
            return text
    return None


def _optional_text(value: Any) -> str | None:
    return str(value).strip() if value is not None and str(value).strip() else None


def _integer(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _timestamp(value: Any) -> datetime | None:
    number = _integer(value)
    return datetime.fromtimestamp(number, tz=UTC) if number else None


def _money_minor(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(
            (Decimal(str(value)) * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP)
        )
    except (InvalidOperation, TypeError, ValueError):
        return None


def _invalid(message: str) -> TikTokApiError:
    return TikTokApiError(message, code="invalid_response", status_code=502)
