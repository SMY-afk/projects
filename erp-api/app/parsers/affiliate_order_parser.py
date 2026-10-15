from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from erp_api.services.affiliate_content_form import affiliate_content_form


class AffiliateOrderParseError(ValueError):
    """Raised when an Affiliate order item cannot be normalized safely."""


def parse_affiliate_order_items(
    payload: Mapping[str, object],
) -> list[dict[str, object]]:
    code = payload.get("code")
    if code not in (None, 0, "0"):
        raise AffiliateOrderParseError(f"Affiliate response code is not zero: {code!r}")

    data = _mapping(payload.get("data"), field="data")
    raw_items = data.get("sku_order_list", [])
    if not isinstance(raw_items, list):
        raise AffiliateOrderParseError("data.sku_order_list must be a list")

    records: list[dict[str, object]] = []
    for index, raw_item in enumerate(raw_items):
        try:
            records.append(parse_affiliate_order_item(raw_item))
        except AffiliateOrderParseError as error:
            raise AffiliateOrderParseError(
                f"Invalid data.sku_order_list[{index}]: {error}"
            ) from error
    return records


def parse_affiliate_order_item(raw_item: object) -> dict[str, object]:
    item = _mapping(raw_item, field="affiliate order item")
    base = _mapping(
        item.get("sku_order_base_info_for_affiliate_seller"),
        field="sku_order_base_info_for_affiliate_seller",
    )
    commission = _optional_mapping(
        item.get("sku_order_commission_info_for_affiliate_seller")
    )
    creator = _optional_mapping(base.get("creator_info"))
    product = _mapping(base.get("product_info"), field="product_info")
    sku_order = _mapping(base.get("sku_order_info"), field="sku_order_info")
    promotion = _optional_mapping(sku_order.get("promotion_position_info"))

    main_order_id = _required_text(sku_order, "main_order_id")
    product_id = _required_text(product, "product_id", fallback="id")
    sku_id = _required_text(sku_order, "sku_id", fallback_mapping=product)
    creator_id = _optional_text(creator, "creator_id")
    campaign_id = _optional_text(sku_order, "campaign_id")
    commission_base, currency = _money(commission.get("est_commission_base"))
    estimated_commission, estimated_currency = _money(
        commission.get("est_standard_commission")
    )
    promotion_type = _optional_int(
        promotion.get("promotion_type"),
        field="promotion_position_info.promotion_type",
    )

    return {
        "main_order_id": main_order_id,
        "creator_id": creator_id,
        "creator_nickname": (
            _optional_text(creator, "creator_nickname")
            or _optional_text(creator, "nickname")
        ),
        "campaign_id": campaign_id,
        "product_id": product_id,
        "product_name": (
            _optional_text(product, "product_name") or _optional_text(product, "title")
        ),
        "image_uri": _optional_text(product, "image_uri"),
        "sku_id": sku_id,
        "sku_name": (
            _optional_text(sku_order, "sku_name") or _optional_text(product, "sku_name")
        ),
        "order_created_at": _timestamp_ms(
            sku_order.get("create_time"),
            field="sku_order_info.create_time",
        ),
        "is_cod": _optional_bool(sku_order.get("is_cod"), field="is_cod"),
        "is_non_same_shop_order": _optional_bool(
            sku_order.get("is_non_same_shop_order"),
            field="is_non_same_shop_order",
        ),
        "cos_type": _optional_scalar_text(commission.get("cos_type")),
        "promotion_id": _optional_text(promotion, "promotion_id"),
        "promotion_type": promotion_type,
        "content_form": affiliate_content_form(promotion_type),
        "commission_base": commission_base,
        "commission_currency": currency or estimated_currency,
        "commission_rate": _percent(commission.get("standard_cos_ratio")),
        "estimated_standard_commission": estimated_commission,
        "source_record_key": _source_key(
            main_order_id,
            sku_id,
            product_id,
            creator_id,
            campaign_id,
        ),
        "raw_data": dict(item),
    }


def _source_key(*values: str | None) -> str:
    raw = "|".join(value or "" for value in values)
    return hashlib.sha256(raw.encode()).hexdigest()


def _money(value: object) -> tuple[Decimal | None, str | None]:
    if value is None:
        return None, None
    money = _mapping(value, field="money")
    amount = money.get("amount")
    return (
        _decimal(amount, field="money.amount") if amount is not None else None,
        _optional_text(money, "currency"),
    )


def _percent(value: object) -> Decimal | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("%"):
        return _decimal(text[:-1], field="percentage") / Decimal(100)
    return _decimal(text, field="percentage")


def _decimal(value: object, *, field: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise AffiliateOrderParseError(f"{field} must be numeric") from error


def _timestamp_ms(value: object, *, field: str) -> datetime:
    if value is None:
        raise AffiliateOrderParseError(f"{field} is required")
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=UTC)
    except (TypeError, ValueError, OSError, OverflowError) as error:
        raise AffiliateOrderParseError(f"{field} is invalid") from error


def _mapping(value: object, *, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise AffiliateOrderParseError(f"{field} must be an object")
    return value


def _optional_mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _required_text(
    value: Mapping[str, object],
    key: str,
    *,
    fallback: str | None = None,
    fallback_mapping: Mapping[str, object] | None = None,
) -> str:
    parsed = _optional_text(value, key)
    if parsed is None and fallback is not None:
        parsed = _optional_text(value, fallback)
    if parsed is None and fallback_mapping is not None:
        parsed = _optional_text(fallback_mapping, key)
    if parsed is None:
        raise AffiliateOrderParseError(f"{key} is required")
    return parsed


def _optional_text(value: Mapping[str, object], key: str) -> str | None:
    return _optional_scalar_text(value.get(key))


def _optional_scalar_text(value: object) -> str | None:
    if value is None or isinstance(value, (dict, list)):
        return None
    parsed = str(value).strip()
    return parsed or None


def _optional_bool(value: object, *, field: str) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise AffiliateOrderParseError(f"{field} must be boolean")
    return value


def _optional_int(value: object, *, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise AffiliateOrderParseError(f"{field} must be integer")
    try:
        return int(str(value).strip())
    except (TypeError, ValueError) as error:
        raise AffiliateOrderParseError(f"{field} must be integer") from error
