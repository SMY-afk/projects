from __future__ import annotations

import csv
import hashlib
import io
from collections.abc import Mapping


class SellerOrderExportParseError(ValueError):
    """Raised when a Seller Center order export cannot be parsed safely."""


_ORDER_ID_HEADERS = ("Order ID", "订单 ID", "订单ID")
_CREATOR_ID_HEADERS = ("Creator ID", "creator_id", "达人 ID", "达人ID")
_CREATOR_HANDLE_HEADERS = (
    "Creator Handle",
    "creator_handle",
    "达人账号",
    "达人用户名",
)


def parse_seller_order_export(content: bytes | str) -> list[dict[str, object]]:
    text = _decode(content)
    reader = csv.DictReader(io.StringIO(text, newline=""))
    headers = [str(value or "").strip() for value in (reader.fieldnames or [])]
    order_header = _find_header(headers, _ORDER_ID_HEADERS)
    creator_id_header = _find_header(headers, _CREATOR_ID_HEADERS)
    creator_handle_header = _find_header(headers, _CREATOR_HANDLE_HEADERS)
    if order_header is None:
        raise SellerOrderExportParseError("Order ID column is required")
    if creator_id_header is None and creator_handle_header is None:
        raise SellerOrderExportParseError(
            "Creator ID or Creator Handle column is required"
        )

    records: dict[str, dict[str, object]] = {}
    for row in reader:
        order_id = _text(row, order_header)
        creator_id = _text(row, creator_id_header)
        creator_handle = _text(row, creator_handle_header)
        if not order_id or not (creator_id or creator_handle):
            continue
        identity = creator_id or creator_handle
        source_key = _source_key(order_id, identity)
        field_name = creator_id_header if creator_id else creator_handle_header
        records[source_key] = {
            "source_system": "seller_order_export",
            "source_record_key": source_key,
            "external_conversion_id": source_key,
            "main_order_id": order_id,
            "match_key_type": "order_id",
            "match_key_value": order_id,
            "creator_external_id": creator_id,
            "operator_subject_candidate": "creator" if creator_id else None,
            "evidence_strength": "exact_order",
            "confidence_score": 0.98 if creator_id else 0.85,
            "evidence_json": {
                "source": "seller_order_export",
                "field_path": f"CSV.{field_name}",
                **({"creator_handle": creator_handle} if creator_handle else {}),
                "creator_identity_verified": True,
                "reason": "seller_order_export_creator",
            },
        }
    return list(records.values())


def _decode(content: bytes | str) -> str:
    if isinstance(content, str):
        return content.removeprefix("\ufeff")
    for encoding in ("utf-8-sig", "utf-16", "gb18030"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise SellerOrderExportParseError("Order export encoding is not supported")


def _find_header(headers: list[str], candidates: tuple[str, ...]) -> str | None:
    normalized = {header.casefold(): header for header in headers}
    return next(
        (
            normalized[candidate.casefold()]
            for candidate in candidates
            if candidate.casefold() in normalized
        ),
        None,
    )


def _text(row: Mapping[str, object], header: str | None) -> str | None:
    if header is None:
        return None
    raw = row.get(header)
    if raw is None or isinstance(raw, (dict, list)):
        return None
    value = str(raw).strip()
    return value or None


def _source_key(*values: object) -> str:
    raw = "|".join(str(value or "") for value in values)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
