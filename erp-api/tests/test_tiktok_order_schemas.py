from datetime import UTC, datetime

import pytest

from erp_api.services.tiktok_order_schemas import (
    TikTokOrderAttributionSignal,
    parse_order_detail_response,
    parse_order_page_response,
)
from erp_api.services.tiktok_transport import TikTokApiError


def test_order_mapping_normalizes_money_status_lines_and_pii() -> None:
    page = parse_order_page_response(
        {
            "data": {
                "orders": [
                    {
                        "id": "order-1",
                        "order_number": "TT-1",
                        "status": "AWAITING_SHIPMENT",
                        "create_time": 1_700_000_000,
                        "update_time": 1_700_000_100,
                        "payment": {"currency": "usd", "total_amount": "12.34"},
                        "line_items": [
                            {
                                "id": "line-1",
                                "product_name": "Toy",
                                "sku_id": "sku-1",
                                "quantity": 2,
                                "sale_price": "6.17",
                                "line_total": "12.34",
                            }
                        ],
                        "recipient_address": {
                            "name": "Buyer",
                            "phone_number": "1234567890",
                            "region_code": "US",
                            "city": "Seattle",
                        },
                    }
                ],
                "next_page_token": "next",
                "total_count": 1,
            }
        }
    )

    order = page.orders[0]
    assert order.status == "awaiting_shipment"
    assert order.currency == "USD"
    assert order.total_amount_minor == 1234
    assert order.placed_at == datetime.fromtimestamp(1_700_000_000, tz=UTC)
    assert order.lines[0].platform_sku_id == "sku-1"
    assert order.recipient and order.recipient.phone == "1234567890"
    assert order.attribution_signal.is_sample_order is None
    assert order.attribution_signal.source_updated_at == datetime.fromtimestamp(
        1_700_000_100, tz=UTC
    )
    assert order.attribution_signal.has_verified_signal is False
    assert not hasattr(order.attribution_signal, "traffic_source_code")
    assert not hasattr(order, "raw_payload")


def test_order_mapping_keeps_package_delivery_option_id() -> None:
    payload = {
        "data": {
            "orders": [
                {
                    "id": "order-fulfillment",
                    "status": "AWAITING_SHIPMENT",
                    "create_time": 1_700_000_000,
                    "update_time": 1_700_000_100,
                    "line_items": [],
                    "packages": [
                        {
                            "id": "package-1",
                            "status": "TO_FULFILL",
                            "delivery_option_id": "delivery-option-1",
                        }
                    ],
                }
            ]
        }
    }

    fulfillment = parse_order_page_response(payload).orders[0].fulfillments[0]

    assert fulfillment.delivery_option_id == "delivery-option-1"


def test_unknown_platform_status_is_preserved_without_breaking_sync() -> None:
    payload = {
        "data": {
            "orders": [
                {
                    "id": "order-2",
                    "status": "NEW_PLATFORM_STATE",
                    "create_time": 1_700_000_000,
                    "update_time": 1_700_000_001,
                    "line_items": [],
                }
            ]
        }
    }

    order = parse_order_page_response(payload).orders[0]

    assert order.status == "unknown"
    assert order.external_status == "NEW_PLATFORM_STATE"
    assert order.attribution_signal.is_sample_order is None


def test_page_keeps_orders_when_attribution_signal_is_missing() -> None:
    page = parse_order_page_response(
        {
            "data": {
                "orders": [
                    {
                        "id": "order-without-signal",
                        "status": "AWAITING_SHIPMENT",
                        "create_time": 1_700_000_000,
                        "update_time": 1_700_000_100,
                        "line_items": [],
                    },
                    {
                        "id": "order-with-signal",
                        "status": "AWAITING_SHIPMENT",
                        "create_time": 1_700_000_000,
                        "update_time": 1_700_000_101,
                        "is_sample_order": True,
                        "line_items": [],
                    },
                ],
                "next_page_token": "",
            }
        }
    )

    assert [order.platform_order_id for order in page.orders] == [
        "order-without-signal",
        "order-with-signal",
    ]
    assert page.orders[0].attribution_signal.is_sample_order is None
    assert page.orders[1].attribution_signal.is_sample_order is True
    assert page.orders[0].attribution_signal.has_verified_signal is False
    assert page.orders[1].attribution_signal.has_verified_signal is True


def test_empty_order_page_without_orders_key_is_a_valid_result() -> None:
    page = parse_order_page_response(
        {"data": {"next_page_token": "", "total_count": 0}}
    )

    assert page.orders == []
    assert page.total_count == 0


def test_order_detail_reads_single_order_from_orders_array() -> None:
    order = parse_order_detail_response(
        {
            "data": {
                "orders": [
                    {
                        "id": "order-1",
                        "status": "AWAITING_SHIPMENT",
                        "create_time": 1_700_000_000,
                        "update_time": 1_700_000_100,
                        "is_sample_order": True,
                        "line_items": [],
                        "packages": [],
                    }
                ]
            }
        }
    )

    assert order.platform_order_id == "order-1"
    assert order.attribution_signal.is_sample_order is True
    assert order.attribution_signal.source_updated_at == datetime.fromtimestamp(
        1_700_000_100, tz=UTC
    )


def test_order_detail_keeps_order_when_attribution_field_is_missing() -> None:
    order = parse_order_detail_response(
        {
            "data": {
                "orders": [
                    {
                        "id": "order-without-signal",
                        "status": "AWAITING_SHIPMENT",
                        "create_time": 1_700_000_000,
                        "update_time": 1_700_000_100,
                        "line_items": [],
                        "packages": [],
                    }
                ]
            }
        }
    )

    assert order.platform_order_id == "order-without-signal"
    assert order.attribution_signal == TikTokOrderAttributionSignal(
        source_updated_at=datetime.fromtimestamp(1_700_000_100, tz=UTC)
    )


def test_invalid_sample_signal_is_not_coerced_into_attribution() -> None:
    order = parse_order_page_response(
        {
            "data": {
                "orders": [
                    {
                        "id": "order-3",
                        "status": "AWAITING_SHIPMENT",
                        "create_time": 1_700_000_000,
                        "update_time": 1_700_000_100,
                        "is_sample_order": "true",
                        "line_items": [],
                    }
                ]
            }
        }
    ).orders[0]

    assert order.attribution_signal.is_sample_order is None


def test_order_detail_rejects_missing_or_multiple_orders() -> None:
    with pytest.raises(TikTokApiError, match="exactly one order"):
        parse_order_detail_response({"data": {"orders": []}})

    with pytest.raises(TikTokApiError, match="exactly one order"):
        parse_order_detail_response(
            {
                "data": {
                    "orders": [
                        {"id": "order-1"},
                        {"id": "order-2"},
                    ]
                }
            }
        )
