from __future__ import annotations

from sqlalchemy import and_, func, or_, select

from erp_api.models.finance_payment import FinancePayment, FinancePaymentStatement
from erp_api.models.finance_statement import FinanceStatement
from erp_api.models.finance_transaction import FinanceTransaction
from erp_api.models.order import Order


def transaction_filters(query) -> list[object]:
    item = FinanceTransaction
    filters = _common_filters(item, query, item.occurred_at)
    if query.statement_id:
        filters.append(item.statement_id == query.statement_id)
    if query.order_id:
        filters.append(item.order_id == query.order_id)
    if query.transaction_type:
        filters.append(item.transaction_type == query.transaction_type)
    if query.is_estimated is not None:
        filters.append(item.is_estimated.is_(query.is_estimated))
    pending = or_(
        item.is_estimated.is_(True),
        func.upper(item.status) == "UNSETTLED",
    )
    final = and_(
        item.is_estimated.is_(False),
        func.upper(item.status) != "UNSETTLED",
    )
    if query.payment_state == "pending":
        filters.append(pending)
    elif query.payment_state == "refunded":
        filters.append(and_(final, item.refund_amount_minor != 0))
    elif query.payment_state == "completed":
        filters.append(and_(final, item.refund_amount_minor == 0))
    if query.keyword and (needle := query.keyword.strip()):
        pattern = f"%{needle}%"
        filters.append(
            or_(
                item.platform_transaction_id.ilike(pattern),
                item.platform_order_id.ilike(pattern),
                item.source_record_key.ilike(pattern),
                item.order_id.in_(
                    select(Order.id).where(Order.order_number.ilike(pattern))
                ),
            )
        )
    return filters


def statement_filters(query) -> list[object]:
    filters = _common_filters(
        FinanceStatement,
        query,
        FinanceStatement.statement_end_at,
    )
    if query.payment_status:
        filters.append(FinanceStatement.payment_status == query.payment_status)
    return filters


def payment_filters(query) -> list[object]:
    occurred_at = func.coalesce(FinancePayment.paid_at, FinancePayment.initiated_at)
    return _common_filters(FinancePayment, query, occurred_at)


def statement_transaction_totals():
    transaction = FinanceTransaction
    return (
        select(
            transaction.statement_id.label("statement_id"),
            func.count(transaction.id).label("transaction_count"),
            func.coalesce(func.sum(transaction.settlement_amount_minor), 0).label(
                "transaction_amount_minor"
            ),
        )
        .where(transaction.statement_id.is_not(None))
        .group_by(transaction.statement_id)
        .subquery()
    )


def statement_payment_totals():
    link = FinancePaymentStatement
    payment = FinancePayment
    return (
        select(
            link.statement_id.label("statement_id"),
            func.count(payment.id.distinct()).label("payment_count"),
            func.coalesce(func.sum(payment.payment_amount_minor), 0).label(
                "payment_amount_minor"
            ),
        )
        .join(payment, payment.id == link.payment_id)
        .group_by(link.statement_id)
        .subquery()
    )


def payment_statement_totals():
    link = FinancePaymentStatement
    statement = FinanceStatement
    return (
        select(
            link.payment_id.label("payment_id"),
            func.count(statement.id.distinct()).label("statement_count"),
            func.coalesce(func.sum(statement.settlement_amount_minor), 0).label(
                "statement_amount_minor"
            ),
        )
        .join(statement, statement.id == link.statement_id)
        .group_by(link.payment_id)
        .subquery()
    )


def _common_filters(model, query, occurred_at) -> list[object]:
    filters: list[object] = []
    if query.shop_id:
        filters.append(model.shop_id == query.shop_id)
    if query.currency:
        filters.append(model.currency == query.currency.upper())
    if query.status:
        filters.append(model.status == query.status)
    if query.window_from:
        filters.append(occurred_at >= query.window_from)
    if query.window_to:
        filters.append(occurred_at < query.window_to)
    return filters
