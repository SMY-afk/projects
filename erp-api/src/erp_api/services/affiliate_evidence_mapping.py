from __future__ import annotations

from collections.abc import Mapping


def build_affiliate_evidence(record: Mapping[str, object]) -> dict[str, object]:
    main_order_id = _required_text(record, "main_order_id")
    source_record_key = _required_text(record, "source_record_key")
    creator_id = _optional_text(record, "creator_id")
    raw = _mapping_or_empty(record.get("raw_data"))
    base = _mapping_or_empty(raw.get("sku_order_base_info_for_affiliate_seller"))
    sku_order = _mapping_or_empty(base.get("sku_order_info"))
    meta_plan = _mapping_or_empty(sku_order.get("meta_plan_info"))
    promotion = _mapping_or_empty(sku_order.get("promotion_position_info"))
    sku_id = _required_text(record, "sku_id")
    return {
        "source_system": "affiliate_order",
        "source_record_key": source_record_key,
        "external_conversion_id": source_record_key,
        "main_order_id": main_order_id,
        "match_key_type": "order_id",
        "match_key_value": main_order_id,
        "creator_external_id": creator_id,
        "product_external_id": _optional_text(record, "product_id"),
        "sku_external_id": sku_id,
        "campaign_external_id": _optional_text(record, "campaign_id"),
        "promotion_external_id": _scalar_text(promotion.get("promotion_id")),
        "operator_subject_candidate": "creator" if creator_id else None,
        "evidence_strength": "exact_order",
        "confidence_score": 0.9 if creator_id else 0.7,
        "source_created_at": record.get("order_created_at"),
        "source_updated_at": record.get("order_created_at"),
        "raw_platform_id": f"affiliate_order:{main_order_id}:{sku_id}",
        "evidence_json": {
            "source": "affiliate_order",
            "reason": "exact_order_link",
            "plan_id": _scalar_text(meta_plan.get("plan_id")),
            "plan_type": _scalar_text(meta_plan.get("plan_type")),
            "promotion_type": _scalar_text(promotion.get("promotion_type")),
            "platform": _scalar_text(sku_order.get("platform")),
            "entry_point_verified": False,
        },
    }


def _required_text(record: Mapping[str, object], key: str) -> str:
    value = _optional_text(record, key)
    if value is None:
        raise ValueError(f"{key} is required")
    return value


def _optional_text(record: Mapping[str, object], key: str) -> str | None:
    return _scalar_text(record.get(key))


def _scalar_text(value: object) -> str | None:
    if value is None or isinstance(value, (dict, list)):
        return None
    parsed = str(value).strip()
    return parsed or None


def _mapping_or_empty(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, Mapping) else {}
