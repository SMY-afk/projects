from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime


class SellerOrderParseError(ValueError):
    """Raised when a Seller Center order response cannot be normalized."""


def parse_seller_order_response(
    payload: Mapping[str, object],
) -> list[dict[str, object]]:
    code = payload.get("code")
    if code not in (None, 0, "0"):
        raise SellerOrderParseError(f"Seller order response code is not zero: {code!r}")
    data = _mapping(payload.get("data"), field="data")
    orders = data.get("main_orders", [])
    if not isinstance(orders, list):
        raise SellerOrderParseError("data.main_orders must be a list")

    evidence_records: list[dict[str, object]] = []
    for index, raw_order in enumerate(orders):
        order = _mapping(raw_order, field=f"data.main_orders[{index}]")
        main_order_id = _required_text(order, "main_order_id")
        evidence_records.extend(_order_evidence(order, main_order_id))
    return evidence_records


def parse_aggregate_response(
    payload: Mapping[str, object],
    *,
    data_type: str,
) -> list[dict[str, object]]:
    """Retain non-order analytics without creating attribution evidence."""

    if not data_type or len(data_type) > 50:
        raise SellerOrderParseError("data_type must contain at most 50 characters")
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:32]
    return [
        {
            "platform_id": f"seller_{data_type}:{digest}",
            "data_type": data_type,
            "raw_data": dict(payload),
        }
    ]


def _order_evidence(
    order: Mapping[str, object],
    main_order_id: str,
) -> list[dict[str, object]]:
    sku_modules = order.get("sku_module", [])
    if not isinstance(sku_modules, list):
        raise SellerOrderParseError("sku_module must be a list")
    source_updated_at = _order_updated_at(order)
    records: list[dict[str, object]] = []
    for sku_index, raw_sku in enumerate(sku_modules):
        sku = _mapping(raw_sku, field=f"sku_module[{sku_index}]")
        product_id = _optional_text(sku, "product_id")
        sku_id = _optional_text(sku, "sku_id")
        line_ids = _text_list(sku.get("order_line_ids")) or [None]
        creator_hint_count = _creator_hint_count(sku)
        for line_id in line_ids:
            source_record_key = _source_key(
                main_order_id,
                line_id,
                product_id,
                sku_id,
            )
            records.append(
                {
                    "source_system": "seller_order_list",
                    "source_record_key": source_record_key,
                    "external_conversion_id": source_record_key,
                    "main_order_id": main_order_id,
                    "platform_order_line_id": line_id,
                    "match_key_type": "order_item_id" if line_id else "order_id",
                    "match_key_value": line_id or main_order_id,
                    "product_external_id": product_id,
                    "sku_external_id": sku_id,
                    "evidence_strength": (
                        "exact_order_line" if line_id else "exact_order"
                    ),
                    "confidence_score": 0.4 if creator_hint_count else 0.3,
                    "source_updated_at": source_updated_at,
                    "evidence_json": {
                        "source": "seller_order_list",
                        "field_path": "data.main_orders[].sku_module[]",
                        "weak_creator_hint_count": creator_hint_count,
                        "creator_identity_verified": False,
                        "reason": "weak_creator_display_only",
                    },
                }
            )
    return records


def _creator_hint_count(sku: Mapping[str, object]) -> int:
    creator_info = sku.get("creator_info_name")
    if not isinstance(creator_info, Mapping):
        return 0
    items = creator_info.get("items")
    if not isinstance(items, list):
        return 0
    return sum(
        1
        for item in items
        if isinstance(item, Mapping) and _optional_text(item, "message_content")
    )


def _order_updated_at(order: Mapping[str, object]) -> datetime | None:
    trade = order.get("trade_order_module")
    if not isinstance(trade, Mapping):
        return None
    raw = trade.get("update_time") or trade.get("create_time")
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        scale = 1000 if raw > 10_000_000_000 else 1
        return datetime.fromtimestamp(raw / scale, tz=UTC)
    try:
        return datetime.fromisoformat(str(raw))
    except ValueError:
        return None


def _source_key(*values: object) -> str:
    raw = "|".join(str(value or "") for value in values)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _mapping(value: object, *, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise SellerOrderParseError(f"{field} must be an object")
    return value


def _required_text(value: Mapping[str, object], key: str) -> str:
    parsed = _optional_text(value, key)
    if parsed is None:
        raise SellerOrderParseError(f"{key} is required")
    return parsed


def _optional_text(value: Mapping[str, object], key: str) -> str | None:
    raw = value.get(key)
    if raw is None or isinstance(raw, (dict, list)):
        return None
    parsed = str(raw).strip()
    return parsed or None


def _text_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]
