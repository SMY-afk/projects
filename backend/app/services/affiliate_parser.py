import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any


def parse_money(data: dict[str, Any] | None) -> tuple[Decimal | None, str | None]:
    if not data:
        return None, None

    amount = data.get("amount")
    currency = data.get("currency")

    parsed_amount = Decimal(str(amount)) if amount is not None else None
    parsed_currency = str(currency) if currency is not None else None
    return parsed_amount, parsed_currency


def parse_percent(value: object | None) -> Decimal | None:
    if value is None or value == "":
        return None

    text = str(value).strip()
    if not text:
        return None
    if text.endswith("%"):
        return Decimal(text[:-1]) / Decimal(100)
    return Decimal(text)


def timestamp_ms_to_datetime(value: object | None) -> datetime | None:
    if value is None or value == "":
        return None

    return datetime.fromtimestamp(int(value) / 1000, tz=UTC)


def make_source_key(
    main_order_id: object | None,
    sku_id: object | None,
    product_id: object | None,
    creator_id: object | None,
    campaign_id: object | None,
) -> str:
    raw = "|".join(
        [
            str(main_order_id or ""),
            str(sku_id or ""),
            str(product_id or ""),
            str(creator_id or ""),
            str(campaign_id or ""),
        ]
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def parse_affiliate_item(item: dict[str, Any]) -> dict[str, Any]:
    base = item.get("sku_order_base_info_for_affiliate_seller") or {}
    commission = item.get("sku_order_commission_info_for_affiliate_seller") or {}

    creator = base.get("creator_info") or {}
    product = base.get("product_info") or {}
    sku_order = base.get("sku_order_info") or {}

    commission_base, currency = parse_money(commission.get("est_commission_base"))
    estimated_commission, _ = parse_money(commission.get("est_standard_commission"))

    main_order_id = sku_order.get("main_order_id")
    campaign_id = sku_order.get("campaign_id")
    creator_id = creator.get("creator_id")
    product_id = product.get("product_id") or product.get("id")
    sku_id = sku_order.get("sku_id") or product.get("sku_id")

    source_record_key = make_source_key(
        main_order_id=main_order_id,
        sku_id=sku_id,
        product_id=product_id,
        creator_id=creator_id,
        campaign_id=campaign_id,
    )

    return {
        "main_order_id": main_order_id,
        "creator_id": creator_id,
        "creator_nickname": creator.get("creator_nickname") or creator.get("nickname"),
        "campaign_id": campaign_id,
        "product_id": product_id,
        "product_name": product.get("product_name") or product.get("title"),
        "image_uri": product.get("image_uri"),
        "sku_id": sku_id,
        "sku_name": sku_order.get("sku_name") or product.get("sku_name"),
        "order_created_at": timestamp_ms_to_datetime(sku_order.get("create_time")),
        "is_cod": sku_order.get("is_cod"),
        "is_non_same_shop_order": sku_order.get("is_non_same_shop_order"),
        "cos_type": commission.get("cos_type"),
        "commission_base": commission_base,
        "commission_currency": currency,
        "commission_rate": parse_percent(commission.get("standard_cos_ratio")),
        "estimated_standard_commission": estimated_commission,
        "source_record_key": source_record_key,
        "raw_data": json.dumps(item, ensure_ascii=False),
    }
