from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class FinanceMoney:
    currency: str
    value: Decimal


@dataclass(frozen=True)
class FinanceStatement:
    id: str
    currency: str
    payment_status: str
    statement_time: datetime
    payment_time: datetime | None
    adjustment_amount: Decimal
    fee_amount: Decimal
    net_sales_amount: Decimal
    revenue_amount: Decimal
    settlement_amount: Decimal
    shipping_cost_amount: Decimal


@dataclass(frozen=True)
class FinanceStatementPage:
    statements: tuple[FinanceStatement, ...]
    next_page_token: str


@dataclass(frozen=True)
class FinancePayment:
    id: str
    status: str
    bank_account_masked: str
    create_time: datetime
    paid_time: datetime | None
    exchange_rate: Decimal
    amount: FinanceMoney
    payment_amount_before_exchange: FinanceMoney
    settlement_amount: FinanceMoney


@dataclass(frozen=True)
class FinancePaymentPage:
    payments: tuple[FinancePayment, ...]
    next_page_token: str


@dataclass(frozen=True)
class FinanceStatementTransaction:
    id: str
    order_id: str | None
    type: str
    order_create_time: datetime
    adjustment_amount: Decimal
    fee_tax_amount: Decimal
    revenue_amount: Decimal
    settlement_amount: Decimal
    shipping_cost_amount: Decimal
    revenue_breakdown: Mapping[str, Decimal]
    fee_tax_breakdown: Mapping[str, Decimal]
    shipping_cost_breakdown: Mapping[str, Decimal]
    supplementary_component: Mapping[str, Decimal]


@dataclass(frozen=True)
class FinanceStatementTransactionPage:
    statement_id: str
    currency: str
    status: str
    create_time: datetime
    payable_amount: Decimal
    total_reserve_amount: Decimal
    total_settlement_amount: Decimal
    total_count: int
    total_settlement_breakdown: Mapping[str, Decimal]
    transactions: tuple[FinanceStatementTransaction, ...]
    next_page_token: str


@dataclass(frozen=True)
class FinanceSkuTransaction:
    sku_id: str
    sku_name: str
    product_name: str
    statement_id: str
    quantity: Decimal
    revenue_amount: Decimal
    fee_tax_amount: Decimal
    shipping_cost_amount: Decimal
    settlement_amount: Decimal
    revenue_breakdown: Mapping[str, Decimal]
    fee_tax_breakdown: Mapping[str, Decimal]
    shipping_cost_breakdown: Mapping[str, Decimal]


@dataclass(frozen=True)
class FinanceOrderTransaction:
    order_id: str
    currency: str
    order_create_time: datetime
    revenue_amount: Decimal
    fee_and_tax_amount: Decimal
    shipping_cost_amount: Decimal
    settlement_amount: Decimal
    total_count: int
    sku_transactions: tuple[FinanceSkuTransaction, ...]


@dataclass(frozen=True)
class FinanceUnsettledTransaction:
    id: str
    order_id: str
    currency: str
    type: str
    status: str
    unsettled_reason: str
    order_create_time: datetime
    estimated_settlement: str
    est_revenue_amount: Decimal
    est_fee_tax_amount: Decimal
    est_shipping_cost_amount: Decimal
    est_settlement_amount: Decimal
    revenue_breakdown: Mapping[str, Decimal]
    fee_tax_breakdown: Mapping[str, Decimal]
    shipping_cost_breakdown: Mapping[str, Decimal]
    estimated: bool = True


@dataclass(frozen=True)
class FinanceUnsettledTransactionPage:
    total_count: int
    sum_est_revenue_amount: Decimal
    sum_est_fee_amount: Decimal
    sum_est_adjustment_amount: Decimal
    sum_est_settlement_amount: Decimal
    transactions: tuple[FinanceUnsettledTransaction, ...]
    next_page_token: str
    estimated: bool = True
