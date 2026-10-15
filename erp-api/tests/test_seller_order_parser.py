import pytest

from app.parsers.seller_order_parser import (
    SellerOrderParseError,
    parse_aggregate_response,
    parse_seller_order_response,
)


def _payload() -> dict[str, object]:
    return {
        "code": 0,
        "data": {
            "main_orders": [
                {
                    "main_order_id": "order-1",
                    "sku_module": [
                        {
                            "order_line_ids": ["line-1", "line-2"],
                            "product_id": "product-1",
                            "sku_id": "sku-1",
                            "creator_info_name": {
                                "items": [{"message_content": "display-only"}]
                            },
                        }
                    ],
                    "trade_order_module": {"update_time": "2026-08-18T00:00:00Z"},
                    "buyer_info_module": {"shipping_address": {"name": "PII"}},
                }
            ]
        },
    }


def test_seller_order_parser_prefers_order_line_keys_and_does_not_promote_hint() -> (
    None
):
    records = parse_seller_order_response(_payload())

    assert len(records) == 2
    assert {item["match_key_type"] for item in records} == {"order_item_id"}
    assert {item["match_key_value"] for item in records} == {"line-1", "line-2"}
    assert all(item["main_order_id"] == "order-1" for item in records)
    assert all(item["product_external_id"] == "product-1" for item in records)
    assert all(item["sku_external_id"] == "sku-1" for item in records)
    assert all("creator_external_id" not in item for item in records)
    assert all(
        item["evidence_json"]["creator_identity_verified"] is False for item in records
    )
    assert "buyer_info_module" not in str(records)


def test_aggregate_parser_retains_raw_payload_without_order_evidence() -> None:
    payload = {"code": 0, "data": {"items": [{"affiliate_video_gmv": "10"}]}}

    records = parse_aggregate_response(payload, data_type="seller_product_analytics")

    assert len(records) == 1
    assert records[0]["data_type"] == "seller_product_analytics"
    assert records[0]["raw_data"] == payload
    assert "main_order_id" not in records[0]


def test_invalid_seller_order_shape_is_rejected() -> None:
    with pytest.raises(SellerOrderParseError):
        parse_seller_order_response({"code": 0, "data": {"main_orders": {}}})
