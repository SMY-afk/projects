from __future__ import annotations

from copy import deepcopy
from decimal import Decimal

import pytest

from erp_api.services.tiktok_finance_schemas import (
    parse_order_transactions_response,
    parse_payments_response,
    parse_statement_transactions_response,
    parse_statements_response,
    parse_unsettled_transactions_response,
)
from erp_api.services.tiktok_transport import TikTokApiError


def test_parse_statements_requires_and_converts_finance_fields() -> None:
    page = parse_statements_response(
        {
            "data": {
                "next_page_token": "next",
                "statements": [
                    {
                        "id": "statement-1",
                        "currency": "USD",
                        "payment_status": "PROCESSING",
                        "statement_time": 1_700_000_000,
                        "payment_time": 1_700_086_400,
                        "adjustment_amount": "-1.25",
                        "fee_amount": "2.10",
                        "net_sales_amount": "18.40",
                        "revenue_amount": "20.50",
                        "settlement_amount": "17.15",
                        "shipping_cost_amount": "0.50",
                    }
                ],
            }
        }
    )

    assert page.next_page_token == "next"
    assert page.statements[0].settlement_amount == Decimal("17.15")
    assert page.statements[0].adjustment_amount == Decimal("-1.25")
    assert page.statements[0].statement_time.tzinfo is not None


def test_parse_payments_masks_bank_account_before_exposing_dto() -> None:
    page = parse_payments_response(
        {
            "data": {
                "next_page_token": "",
                "payments": [
                    {
                        "id": "payment-1",
                        "status": "PAID",
                        "bank_account": "1234567890",
                        "create_time": 1_700_000_000,
                        "paid_time": 1_700_086_400,
                        "exchange_rate": "1.000000",
                        "amount": {"currency": "USD", "value": "17.15"},
                        "payment_amount_before_exchange": {
                            "currency": "USD",
                            "value": "17.15",
                        },
                        "settlement_amount": {
                            "currency": "USD",
                            "value": "17.15",
                        },
                    }
                ],
            }
        }
    )

    payment = page.payments[0]
    assert payment.bank_account_masked == "******7890"
    assert "1234567890" not in repr(payment)
    assert payment.amount.value == Decimal("17.15")


def test_parse_payments_allows_missing_paid_time_for_pending_payment() -> None:
    payload = {
        "data": {
            "next_page_token": "",
            "payments": [
                {
                    "id": "payment-2",
                    "status": "PROCESSING",
                    "bank_account": "",
                    "create_time": 1_700_000_000,
                    "exchange_rate": "1",
                    "amount": {"currency": "USD", "value": "1.00"},
                    "payment_amount_before_exchange": {
                        "currency": "USD",
                        "value": "1.00",
                    },
                    "settlement_amount": {"currency": "USD", "value": "1.00"},
                }
            ],
        }
    }

    assert parse_payments_response(payload).payments[0].paid_time is None


def test_parse_statement_transactions_flattens_strict_breakdowns() -> None:
    page = parse_statement_transactions_response(_statement_transactions_payload())

    transaction = page.transactions[0]
    assert page.total_settlement_amount == Decimal("8.50")
    assert transaction.revenue_breakdown == {"subtotal": Decimal("10.00")}
    assert transaction.fee_tax_breakdown == {
        "fee.platform_fee": Decimal("1.00"),
        "tax.sales_tax": Decimal("0.25"),
    }


def test_parse_order_transactions_preserves_sku_finance_detail() -> None:
    result = parse_order_transactions_response(_order_transactions_payload())

    sku = result.sku_transactions[0]
    assert result.order_id == "order-1"
    assert sku.quantity == Decimal(2)
    assert sku.statement_id == "statement-1"
    assert sku.shipping_cost_breakdown == {"shipping_fee": Decimal("0.50")}


def test_parse_unsettled_transactions_marks_estimates_explicitly() -> None:
    page = parse_unsettled_transactions_response(_unsettled_payload())

    assert page.estimated is True
    assert page.transactions[0].estimated is True
    assert page.transactions[0].estimated_settlement == "Delivered + 5 days"
    assert page.sum_est_settlement_amount == Decimal("8.50")


def test_statement_transaction_accepts_null_optional_order_id() -> None:
    payload = _statement_transactions_payload()
    payload["data"]["transactions"][0]["order_id"] = None

    page = parse_statement_transactions_response(payload)

    assert page.transactions[0].order_id is None


def test_statement_transaction_rejects_non_text_order_id() -> None:
    payload = _statement_transactions_payload()
    payload["data"]["transactions"][0]["order_id"] = 123

    with pytest.raises(TikTokApiError):
        parse_statement_transactions_response(payload)


@pytest.mark.parametrize(
    ("parser", "payload"),
    [
        (parse_statements_response, {"data": {"statements": {}}}),
        (parse_payments_response, {"data": {"payments": [{"id": "p"}]}}),
        (
            parse_statement_transactions_response,
            {"data": {"transactions": [], "currency": "usd"}},
        ),
        (parse_order_transactions_response, {"data": {"order_id": "o"}}),
        (parse_unsettled_transactions_response, {"data": {"transactions": []}}),
    ],
)
def test_finance_parsers_reject_missing_or_wrong_typed_known_fields(
    parser, payload
) -> None:
    with pytest.raises(TikTokApiError) as error:
        parser(payload)

    assert error.value.code == "invalid_finance_response"


def test_finance_parser_rejects_float_and_non_finite_money() -> None:
    float_payload = _statement_transactions_payload()
    float_payload["data"]["transactions"][0]["settlement_amount"] = 8.5
    with pytest.raises(TikTokApiError):
        parse_statement_transactions_response(float_payload)

    infinite_payload = deepcopy(_unsettled_payload())
    infinite_payload["data"]["sum_est_settlement_amount"] = "Infinity"
    with pytest.raises(TikTokApiError):
        parse_unsettled_transactions_response(infinite_payload)


def _statement_transactions_payload() -> dict:
    return {
        "data": {
            "id": "statement-1",
            "currency": "USD",
            "status": "PAID",
            "create_time": 1_700_000_000,
            "payable_amount": "8.50",
            "total_reserve_amount": "0.00",
            "total_settlement_amount": "8.50",
            "total_count": 1,
            "next_page_token": "",
            "total_settlement_breakdown": {
                "total_adjustment_amount": "-0.25",
                "total_fee_tax_amount": "1.25",
                "total_revenue_amount": "10.00",
                "total_shipping_cost_amount": "0.00",
            },
            "transactions": [
                {
                    "id": "transaction-1",
                    "order_id": "order-1",
                    "type": "ORDER",
                    "order_create_time": 1_699_000_000,
                    "adjustment_amount": "-0.25",
                    "fee_tax_amount": "1.25",
                    "revenue_amount": "10.00",
                    "settlement_amount": "8.50",
                    "shipping_cost_amount": "0.00",
                    "revenue_breakdown": {"subtotal": "10.00"},
                    "fee_tax_breakdown": {
                        "fee": {"platform_fee": "1.00"},
                        "tax": {"sales_tax": "0.25"},
                    },
                    "shipping_cost_breakdown": {},
                    "supplementary_component": {},
                }
            ],
        }
    }


def _order_transactions_payload() -> dict:
    return {
        "data": {
            "order_id": "order-1",
            "currency": "USD",
            "order_create_time": 1_699_000_000,
            "revenue_amount": "10.00",
            "fee_and_tax_amount": "1.00",
            "shipping_cost_amount": "0.50",
            "settlement_amount": "8.50",
            "total_count": 1,
            "sku_transactions": [
                {
                    "sku_id": "sku-1",
                    "sku_name": "Blue",
                    "product_name": "Toy",
                    "statement_id": "statement-1",
                    "quantity": "2",
                    "revenue_amount": "10.00",
                    "fee_tax_amount": "1.00",
                    "shipping_cost_amount": "0.50",
                    "settlement_amount": "8.50",
                    "revenue_breakdown": {"subtotal": "10.00"},
                    "fee_tax_breakdown": {"fee": {"platform_fee": "1.00"}},
                    "shipping_cost_breakdown": {"shipping_fee": "0.50"},
                }
            ],
        }
    }


def _unsettled_payload() -> dict:
    return {
        "data": {
            "next_page_token": "",
            "total_count": 1,
            "sum_est_revenue_amount": "10.00",
            "sum_est_fee_amount": "1.00",
            "sum_est_adjustment_amount": "0.00",
            "sum_est_settlement_amount": "8.50",
            "transactions": [
                {
                    "id": "unsettled-1",
                    "order_id": "order-1",
                    "currency": "USD",
                    "type": "ORDER",
                    "status": "PROCESSING",
                    "unsettled_reason": "ORDER_NOT_SETTLED",
                    "order_create_time": 1_699_000_000,
                    "estimated_settlement": "Delivered + 5 days",
                    "est_revenue_amount": "10.00",
                    "est_fee_tax_amount": "1.00",
                    "est_shipping_cost_amount": "0.50",
                    "est_settlement_amount": "8.50",
                    "revenue_breakdown": {"subtotal": "10.00"},
                    "fee_tax_breakdown": {"fee": {"platform_fee": "1.00"}},
                    "shipping_cost_breakdown": {"shipping_fee": "0.50"},
                }
            ],
        }
    }
