from __future__ import annotations

from sqlalchemy import case, func, select

from erp_api.models.finance_payment import FinancePayment
from erp_api.models.finance_statement import FinanceStatement
from erp_api.models.finance_transaction import FinanceTransaction
from erp_api.models.finance_transaction_component import FinanceTransactionComponent
from erp_api.services.finance_repository_queries import (
    payment_filters,
    payment_statement_totals,
    statement_filters,
    statement_transaction_totals,
    transaction_filters,
)


async def load_finance_overview(database, tenant_id, query):
    async for session in database.session(tenant_id):
        transactions = await session.execute(_transaction_totals(query))
        trend = await session.execute(_trend_totals(query))
        components = await session.execute(_component_totals(query))
        payments = await session.execute(_payment_totals(query))
        statement_differences = await session.execute(_statement_differences(query))
        payment_differences = await session.execute(_payment_differences(query))
        result: dict[str, dict[str, object]] = {}
        for row in transactions:
            result[row.currency] = {
                "currency": row.currency,
                "gross_revenue_minor": int(row.revenue or 0),
                "refund_amount_minor": int(row.refund or 0),
                "shipping_amount_minor": int(row.shipping or 0),
                "fee_amount_minor": int(row.fee or 0),
                "adjustment_amount_minor": int(row.adjustment or 0),
                "settlement_amount_minor": int(row.settlement or 0),
                "final_count": int(row.final_count or 0),
                "estimated_count": int(row.estimated_count or 0),
                "trend": [],
            }
        for row in trend:
            points = _currency(result, row.currency).setdefault("trend", [])
            points.append(
                {
                    "date": row.date,
                    "revenue_amount_minor": int(row.revenue or 0),
                    "refund_amount_minor": int(row.refund or 0),
                    "fee_amount_minor": int(row.fee or 0),
                    "settlement_amount_minor": int(row.settlement or 0),
                }
            )
        for row in components:
            item = _currency(result, row.currency)
            item["affiliate_commission_minor"] = int(row.affiliate or 0)
            item["tax_amount_minor"] = int(row.tax or 0)
        for row in payments:
            _currency(result, row.currency)["paid_amount_minor"] = int(row.amount or 0)
        for row in statement_differences:
            _currency(result, row.currency)[
                "statement_transaction_difference_minor"
            ] = int(row.difference or 0)
        for row in payment_differences:
            _currency(result, row.currency)["payment_statement_difference_minor"] = int(
                row.difference or 0
            )
        for item in result.values():
            affiliate = int(item.get("affiliate_commission_minor", 0))
            item["platform_fee_minor"] = (
                int(item.get("fee_amount_minor", 0)) - affiliate
            )
        return [_complete(item) for _, item in sorted(result.items())]
    raise RuntimeError("Tenant database session was not created.")


def _transaction_totals(query):
    item = FinanceTransaction
    return (
        select(
            item.currency,
            func.sum(item.revenue_amount_minor).label("revenue"),
            func.sum(item.refund_amount_minor).label("refund"),
            func.sum(item.shipping_amount_minor).label("shipping"),
            func.sum(item.fee_amount_minor).label("fee"),
            func.sum(item.adjustment_amount_minor).label("adjustment"),
            func.sum(item.settlement_amount_minor).label("settlement"),
            func.sum(case((item.is_estimated.is_(False), 1), else_=0)).label(
                "final_count"
            ),
            func.sum(case((item.is_estimated.is_(True), 1), else_=0)).label(
                "estimated_count"
            ),
        )
        .where(*transaction_filters(query))
        .group_by(item.currency)
    )


def _component_totals(query):
    component = FinanceTransactionComponent
    transaction = FinanceTransaction
    code = func.lower(component.component_code)
    return (
        select(
            transaction.currency,
            func.sum(
                case((code.like("%affiliate%"), component.amount_minor), else_=0)
            ).label("affiliate"),
            func.sum(case((code.like("%tax%"), component.amount_minor), else_=0)).label(
                "tax"
            ),
        )
        .join(transaction, transaction.id == component.transaction_id)
        .where(*transaction_filters(query))
        .group_by(transaction.currency)
    )


def _trend_totals(query):
    item = FinanceTransaction
    day = func.date_trunc("day", item.occurred_at)
    return (
        select(
            day.label("date"),
            item.currency,
            func.sum(item.revenue_amount_minor).label("revenue"),
            func.sum(item.refund_amount_minor).label("refund"),
            func.sum(item.fee_amount_minor).label("fee"),
            func.sum(item.settlement_amount_minor).label("settlement"),
        )
        .where(*transaction_filters(query))
        .group_by(day, item.currency)
        .order_by(day, item.currency)
    )


def _payment_totals(query):
    item = FinancePayment
    return (
        select(item.currency, func.sum(item.payment_amount_minor).label("amount"))
        .where(*payment_filters(query))
        .group_by(item.currency)
    )


def _statement_differences(query):
    item = FinanceStatement
    totals = statement_transaction_totals()
    difference = item.settlement_amount_minor - func.coalesce(
        totals.c.transaction_amount_minor, 0
    )
    return (
        select(item.currency, func.sum(difference).label("difference"))
        .outerjoin(totals, totals.c.statement_id == item.id)
        .where(*statement_filters(query))
        .group_by(item.currency)
    )


def _payment_differences(query):
    item = FinancePayment
    totals = payment_statement_totals()
    difference = item.payment_amount_minor - func.coalesce(
        totals.c.statement_amount_minor, 0
    )
    return (
        select(item.currency, func.sum(difference).label("difference"))
        .outerjoin(totals, totals.c.payment_id == item.id)
        .where(*payment_filters(query))
        .group_by(item.currency)
    )


def _currency(result, currency):
    return result.setdefault(currency, {"currency": currency})


def _complete(item):
    defaults = (
        "gross_revenue_minor",
        "refund_amount_minor",
        "shipping_amount_minor",
        "fee_amount_minor",
        "platform_fee_minor",
        "affiliate_commission_minor",
        "tax_amount_minor",
        "adjustment_amount_minor",
        "settlement_amount_minor",
        "paid_amount_minor",
        "statement_transaction_difference_minor",
        "payment_statement_difference_minor",
        "final_count",
        "estimated_count",
    )
    for key in defaults:
        item.setdefault(key, 0)
    item.setdefault("trend", [])
    return item
