from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from erp_api.services.tiktok_finance_models import (
    FinanceOrderTransaction,
    FinanceSkuTransaction,
    FinanceStatementTransaction,
    FinanceStatementTransactionPage,
    FinanceUnsettledTransaction,
    FinanceUnsettledTransactionPage,
)
from erp_api.services.tiktok_finance_parsing import (
    breakdown,
    count,
    currency,
    data_object,
    invalid,
    list_value,
    money,
    optional_text,
    required_text,
    timestamp,
)


def parse_statement_transactions_response(
    payload: Mapping[str, Any],
) -> FinanceStatementTransactionPage:
    data = data_object(payload)
    token = _page_token(data)
    raw_transactions = list_value(data, "transactions")
    return FinanceStatementTransactionPage(
        statement_id=required_text(data, "id"),
        currency=currency(data),
        status=required_text(data, "status"),
        create_time=timestamp(data, "create_time"),
        payable_amount=money(data, "payable_amount"),
        total_reserve_amount=money(data, "total_reserve_amount"),
        total_settlement_amount=money(data, "total_settlement_amount"),
        total_count=count(data),
        total_settlement_breakdown=breakdown(data, "total_settlement_breakdown"),
        transactions=tuple(_statement_transaction(item) for item in raw_transactions),
        next_page_token=token,
    )


def parse_order_transactions_response(
    payload: Mapping[str, Any],
) -> FinanceOrderTransaction:
    data = data_object(payload)
    raw_skus = list_value(data, "sku_transactions")
    return FinanceOrderTransaction(
        order_id=required_text(data, "order_id"),
        currency=currency(data),
        order_create_time=timestamp(data, "order_create_time"),
        revenue_amount=money(data, "revenue_amount"),
        fee_and_tax_amount=money(data, "fee_and_tax_amount"),
        shipping_cost_amount=money(data, "shipping_cost_amount"),
        settlement_amount=money(data, "settlement_amount"),
        total_count=count(data),
        sku_transactions=tuple(_sku_transaction(item) for item in raw_skus),
    )


def parse_unsettled_transactions_response(
    payload: Mapping[str, Any],
) -> FinanceUnsettledTransactionPage:
    data = data_object(payload)
    token = _page_token(data)
    raw_transactions = list_value(data, "transactions")
    return FinanceUnsettledTransactionPage(
        total_count=count(data),
        sum_est_revenue_amount=money(data, "sum_est_revenue_amount"),
        sum_est_fee_amount=money(data, "sum_est_fee_amount"),
        sum_est_adjustment_amount=money(data, "sum_est_adjustment_amount"),
        sum_est_settlement_amount=money(data, "sum_est_settlement_amount"),
        transactions=tuple(_unsettled_transaction(item) for item in raw_transactions),
        next_page_token=token,
    )


def _statement_transaction(value: Any) -> FinanceStatementTransaction:
    data = _mapping(value, "statement transaction")
    return FinanceStatementTransaction(
        id=required_text(data, "id"),
        order_id=optional_text(data, "order_id"),
        type=required_text(data, "type"),
        order_create_time=timestamp(data, "order_create_time"),
        adjustment_amount=money(data, "adjustment_amount"),
        fee_tax_amount=money(data, "fee_tax_amount"),
        revenue_amount=money(data, "revenue_amount"),
        settlement_amount=money(data, "settlement_amount"),
        shipping_cost_amount=money(data, "shipping_cost_amount"),
        revenue_breakdown=breakdown(data, "revenue_breakdown"),
        fee_tax_breakdown=breakdown(data, "fee_tax_breakdown"),
        shipping_cost_breakdown=breakdown(data, "shipping_cost_breakdown"),
        supplementary_component=breakdown(data, "supplementary_component"),
    )


def _sku_transaction(value: Any) -> FinanceSkuTransaction:
    data = _mapping(value, "SKU transaction")
    return FinanceSkuTransaction(
        sku_id=required_text(data, "sku_id"),
        sku_name=required_text(data, "sku_name"),
        product_name=required_text(data, "product_name"),
        statement_id=required_text(data, "statement_id"),
        quantity=money(data, "quantity"),
        revenue_amount=money(data, "revenue_amount"),
        fee_tax_amount=money(data, "fee_tax_amount"),
        shipping_cost_amount=money(data, "shipping_cost_amount"),
        settlement_amount=money(data, "settlement_amount"),
        revenue_breakdown=breakdown(data, "revenue_breakdown"),
        fee_tax_breakdown=breakdown(data, "fee_tax_breakdown"),
        shipping_cost_breakdown=breakdown(data, "shipping_cost_breakdown"),
    )


def _unsettled_transaction(value: Any) -> FinanceUnsettledTransaction:
    data = _mapping(value, "unsettled transaction")
    return FinanceUnsettledTransaction(
        id=required_text(data, "id"),
        order_id=required_text(data, "order_id"),
        currency=currency(data),
        type=required_text(data, "type"),
        status=required_text(data, "status"),
        unsettled_reason=required_text(data, "unsettled_reason"),
        order_create_time=timestamp(data, "order_create_time"),
        estimated_settlement=required_text(data, "estimated_settlement"),
        est_revenue_amount=money(data, "est_revenue_amount"),
        est_fee_tax_amount=money(data, "est_fee_tax_amount"),
        est_shipping_cost_amount=money(data, "est_shipping_cost_amount"),
        est_settlement_amount=money(data, "est_settlement_amount"),
        revenue_breakdown=breakdown(data, "revenue_breakdown"),
        fee_tax_breakdown=breakdown(data, "fee_tax_breakdown"),
        shipping_cost_breakdown=breakdown(data, "shipping_cost_breakdown"),
    )


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise invalid(f"TikTok Finance {label} was not an object.")
    return value


def _page_token(data: Mapping[str, Any]) -> str:
    value = data.get("next_page_token")
    if not isinstance(value, str):
        raise invalid("TikTok Finance page token was not a string.")
    return value
