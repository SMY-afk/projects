from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from erp_api.services.tiktok_finance_models import (
    FinanceMoney,
    FinancePayment,
    FinancePaymentPage,
    FinanceStatement,
    FinanceStatementPage,
)
from erp_api.services.tiktok_finance_parsing import (
    currency,
    data_object,
    invalid,
    list_value,
    money,
    object_value,
    optional_timestamp,
    required_text,
    timestamp,
)
from erp_api.services.tiktok_finance_transaction_schemas import (
    parse_order_transactions_response,
    parse_statement_transactions_response,
    parse_unsettled_transactions_response,
)

__all__ = [
    "parse_order_transactions_response",
    "parse_payments_response",
    "parse_statement_transactions_response",
    "parse_statements_response",
    "parse_unsettled_transactions_response",
]


def parse_statements_response(
    payload: Mapping[str, Any],
) -> FinanceStatementPage:
    data = data_object(payload)
    token = _page_token(data)
    raw_statements = list_value(data, "statements")
    return FinanceStatementPage(
        statements=tuple(_statement(item) for item in raw_statements),
        next_page_token=token,
    )


def parse_payments_response(payload: Mapping[str, Any]) -> FinancePaymentPage:
    data = data_object(payload)
    token = _page_token(data)
    raw_payments = list_value(data, "payments")
    return FinancePaymentPage(
        payments=tuple(_payment(item) for item in raw_payments),
        next_page_token=token,
    )


def _statement(value: Any) -> FinanceStatement:
    if not isinstance(value, Mapping):
        raise invalid("TikTok Finance statement was not an object.")
    return FinanceStatement(
        id=required_text(value, "id"),
        currency=currency(value),
        payment_status=required_text(value, "payment_status"),
        statement_time=timestamp(value, "statement_time"),
        payment_time=optional_timestamp(value, "payment_time"),
        adjustment_amount=money(value, "adjustment_amount"),
        fee_amount=money(value, "fee_amount"),
        net_sales_amount=money(value, "net_sales_amount"),
        revenue_amount=money(value, "revenue_amount"),
        settlement_amount=money(value, "settlement_amount"),
        shipping_cost_amount=money(value, "shipping_cost_amount"),
    )


def _payment(value: Any) -> FinancePayment:
    if not isinstance(value, Mapping):
        raise invalid("TikTok Finance payment was not an object.")
    bank_account = value.get("bank_account")
    if not isinstance(bank_account, str):
        raise invalid("TikTok Finance field bank_account was not a string.")
    return FinancePayment(
        id=required_text(value, "id"),
        status=required_text(value, "status"),
        bank_account_masked=_mask_bank_account(bank_account),
        create_time=timestamp(value, "create_time"),
        paid_time=optional_timestamp(value, "paid_time"),
        exchange_rate=money(value, "exchange_rate"),
        amount=_money_object(value, "amount"),
        payment_amount_before_exchange=_money_object(
            value, "payment_amount_before_exchange"
        ),
        settlement_amount=_money_object(value, "settlement_amount"),
    )


def _money_object(data: Mapping[str, Any], key: str) -> FinanceMoney:
    value = object_value(data, key)
    return FinanceMoney(currency=currency(value), value=money(value, "value"))


def _page_token(data: Mapping[str, Any]) -> str:
    value = data.get("next_page_token")
    if not isinstance(value, str):
        raise invalid("TikTok Finance page token was not a string.")
    return value


def _mask_bank_account(value: str) -> str:
    if not value:
        return "****"
    visible = value[-4:]
    return f"{'*' * max(4, len(value) - len(visible))}{visible}"
