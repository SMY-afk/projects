import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from app.parsers.affiliate_order_parser import (
    AffiliateOrderParseError,
    parse_affiliate_order_item,
    parse_affiliate_order_items,
)

FIXTURE_PATH = Path("backend/tests/data/affiliate_test.json")


def test_real_affiliate_fixture_produces_50_normalized_records() -> None:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    records = parse_affiliate_order_items(payload)

    assert len(records) == 50
    assert len({record["source_record_key"] for record in records}) == 50


def test_real_affiliate_item_maps_money_time_and_keeps_raw_json() -> None:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    raw_item = payload["data"]["sku_order_list"][0]
    sku_order = raw_item["sku_order_base_info_for_affiliate_seller"]["sku_order_info"]

    parsed = parse_affiliate_order_item(raw_item)

    assert parsed["main_order_id"] == sku_order["main_order_id"]
    assert parsed["sku_id"] == sku_order["sku_id"]
    assert parsed["commission_base"] == Decimal("97.8")
    assert parsed["commission_currency"] == "USD"
    assert parsed["commission_rate"] == Decimal("0.15")
    assert parsed["estimated_standard_commission"] == Decimal("14.67")
    assert (
        parsed["promotion_id"] == sku_order["promotion_position_info"]["promotion_id"]
    )
    assert parsed["promotion_type"] == 2
    assert parsed["content_form"] == "video"
    assert parsed["order_created_at"] == datetime.fromtimestamp(
        sku_order["create_time"] / 1000,
        tz=UTC,
    )
    assert parsed["raw_data"] == raw_item


def test_missing_stable_identifiers_are_rejected() -> None:
    with pytest.raises(AffiliateOrderParseError, match="product_id is required"):
        parse_affiliate_order_item(
            {
                "sku_order_base_info_for_affiliate_seller": {
                    "product_info": {},
                    "sku_order_info": {
                        "main_order_id": "main-1",
                        "sku_id": "sku-1",
                        "create_time": 1_789_000_000_000,
                    },
                }
            }
        )


@pytest.mark.parametrize(
    ("ratio", "expected"),
    [
        ("15%", Decimal("0.15")),
        ("0.15", Decimal("0.15")),
        ("", None),
    ],
)
def test_legacy_commission_ratio_formats_remain_supported(
    ratio: str,
    expected: Decimal | None,
) -> None:
    parsed = parse_affiliate_order_item(
        {
            "sku_order_base_info_for_affiliate_seller": {
                "creator_info": {"nickname": "Legacy Creator"},
                "product_info": {
                    "id": "product-legacy",
                    "title": "Legacy Product",
                    "sku_id": "sku-legacy",
                    "sku_name": "Legacy SKU",
                },
                "sku_order_info": {
                    "main_order_id": "main-legacy",
                    "create_time": 1_789_000_000_000,
                },
            },
            "sku_order_commission_info_for_affiliate_seller": {
                "standard_cos_ratio": ratio,
            },
        }
    )

    assert parsed["creator_nickname"] == "Legacy Creator"
    assert parsed["product_id"] == "product-legacy"
    assert parsed["product_name"] == "Legacy Product"
    assert parsed["sku_id"] == "sku-legacy"
    assert parsed["sku_name"] == "Legacy SKU"
    assert parsed["commission_rate"] == expected
    assert (
        parsed["source_record_key"]
        == parse_affiliate_order_item(parsed["raw_data"])["source_record_key"]
    )


@pytest.mark.parametrize(
    ("promotion_type", "content_form"),
    [
        (1, "product_showcase"),
        (2, "video"),
        (3, "live"),
        (5, "affiliate_product_page"),
        (6, "external_traffic_plan"),
        (99, None),
    ],
)
def test_seller_center_content_form_mapping(
    promotion_type: int,
    content_form: str | None,
) -> None:
    parsed = parse_affiliate_order_item(
        {
            "sku_order_base_info_for_affiliate_seller": {
                "product_info": {"product_id": "product-1"},
                "sku_order_info": {
                    "main_order_id": "main-1",
                    "sku_id": "sku-1",
                    "create_time": 1_789_000_000_000,
                    "promotion_position_info": {
                        "promotion_id": "promotion-1",
                        "promotion_type": promotion_type,
                    },
                },
            }
        }
    )

    assert parsed["promotion_type"] == promotion_type
    assert parsed["promotion_id"] == "promotion-1"
    assert parsed["content_form"] == content_form
