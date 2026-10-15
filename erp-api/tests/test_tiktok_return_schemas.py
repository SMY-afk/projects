from datetime import UTC, datetime

from erp_api.services.tiktok_return_schemas import parse_return_page_response


def test_parse_realistic_return_page_preserves_platform_identity_and_line_link() -> (
    None
):
    page = parse_return_page_response(
        {
            "data": {
                "return_orders": [
                    {
                        "return_id": "return-1",
                        "order_id": "order-1",
                        "return_type": "RETURN_AND_REFUND",
                        "return_status": "BUYER_SHIPPED_ITEM",
                        "return_reason": "no_longer_needed",
                        "return_reason_text": "No longer needed",
                        "create_time": 1_700_000_000,
                        "update_time": 1_700_000_100,
                        "refund_amount": {"currency": "USD", "refund_total": "12.34"},
                        "return_line_items": [
                            {
                                "return_line_item_id": "return-line-1",
                                "order_line_item_id": "order-line-1",
                                "seller_sku": "SKU-1",
                            }
                        ],
                    }
                ],
                "next_page_token": "next",
                "total_count": 1,
            }
        }
    )

    record = page.returns[0]
    assert record.platform_return_id == "return-1"
    assert record.platform_order_id == "order-1"
    assert record.request_type == "return"
    assert record.platform_status == "BUYER_SHIPPED_ITEM"
    assert record.created_at == datetime.fromtimestamp(1_700_000_000, tz=UTC)
    assert record.refund_amount_minor == 1234
    assert record.lines[0].platform_order_line_id == "order-line-1"
    assert page.next_page_token == "next"


def test_refund_only_is_not_misclassified_as_physical_return() -> None:
    page = parse_return_page_response(
        {
            "data": {
                "return_orders": [
                    {
                        "return_id": "refund-1",
                        "order_id": "order-1",
                        "return_type": "REFUND",
                        "return_status": "RETURN_OR_REFUND_REQUEST_COMPLETE",
                        "return_reason": "defective",
                        "create_time": 1_700_000_000,
                        "update_time": 1_700_000_100,
                        "return_line_items": [
                            {
                                "return_line_item_id": "refund-line-1",
                                "order_line_item_id": "order-line-1",
                            }
                        ],
                    }
                ]
            }
        }
    )

    assert page.returns[0].request_type == "refund"
    assert page.returns[0].status == "approved"
