from __future__ import annotations

from sqlalchemy import func, select

from erp_api.models.finance_payment import FinancePayment
from erp_api.models.finance_statement import FinanceStatement
from erp_api.models.finance_transaction import FinanceTransaction
from erp_api.services.finance_repository_queries import (
    payment_filters,
    payment_statement_totals,
    statement_filters,
    statement_transaction_totals,
    transaction_filters,
)


async def load_reconciliation(database, tenant_id, query, *, limit: int = 100):
    async for session in database.session(tenant_id):
        groups = await _issue_groups(session, query, limit)
        items = [item for group in groups for item in group]
        items.sort(key=lambda item: item["occurred_at"], reverse=True)
        total = sum(await _issue_counts(session, query))
        return {"items": items[:limit], "total": total}
    raise RuntimeError("Tenant database session was not created.")


async def _issue_groups(session, query, limit):
    transaction = FinanceTransaction
    tx_expected = (
        transaction.revenue_amount_minor
        + transaction.shipping_amount_minor
        + transaction.fee_amount_minor
        + transaction.adjustment_amount_minor
    )
    tx_rows = await session.execute(
        select(transaction, tx_expected.label("expected"))
        .where(
            *transaction_filters(query),
            transaction.settlement_amount_minor != tx_expected,
        )
        .limit(limit)
    )
    missing_rows = await session.scalars(
        select(transaction)
        .where(
            *transaction_filters(query),
            transaction.platform_order_id.is_not(None),
            transaction.order_id.is_(None),
        )
        .limit(limit)
    )
    statement_rows = await session.execute(_statement_issue_select(query).limit(limit))
    payment_rows = await session.execute(_payment_issue_select(query).limit(limit))
    return [
        [_transaction_issue(row[0], int(row.expected)) for row in tx_rows],
        [_missing_order_issue(item) for item in missing_rows],
        [_statement_issue(row) for row in statement_rows],
        [_payment_issue(row) for row in payment_rows],
    ]


async def _issue_counts(session, query):
    transaction = FinanceTransaction
    expected = (
        transaction.revenue_amount_minor
        + transaction.shipping_amount_minor
        + transaction.fee_amount_minor
        + transaction.adjustment_amount_minor
    )
    tx = await session.scalar(
        select(func.count())
        .select_from(transaction)
        .where(
            *transaction_filters(query), transaction.settlement_amount_minor != expected
        )
    )
    missing = await session.scalar(
        select(func.count())
        .select_from(transaction)
        .where(
            *transaction_filters(query),
            transaction.platform_order_id.is_not(None),
            transaction.order_id.is_(None),
        )
    )
    statement = await session.scalar(
        select(func.count()).select_from(_statement_issue_select(query).subquery())
    )
    payment = await session.scalar(
        select(func.count()).select_from(_payment_issue_select(query).subquery())
    )
    return int(tx or 0), int(missing or 0), int(statement or 0), int(payment or 0)


def _statement_issue_select(query):
    item = FinanceStatement
    totals = statement_transaction_totals()
    actual = item.settlement_amount_minor
    expected = func.coalesce(totals.c.transaction_amount_minor, 0)
    return (
        select(item, expected.label("expected"))
        .outerjoin(totals, totals.c.statement_id == item.id)
        .where(*statement_filters(query), actual != expected)
    )


def _payment_issue_select(query):
    item = FinancePayment
    totals = payment_statement_totals()
    expected = func.coalesce(totals.c.statement_amount_minor, 0)
    count = func.coalesce(totals.c.statement_count, 0)
    return (
        select(item, expected.label("expected"), count.label("linked_count"))
        .outerjoin(totals, totals.c.payment_id == item.id)
        .where(*payment_filters(query), item.payment_amount_minor != expected)
    )


def _base(
    kind, entity_type, entity_id, reference, currency, expected, actual, occurred
):
    difference = actual - expected
    return {
        "kind": kind,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "reference": reference,
        "currency": currency,
        "expected_amount_minor": expected,
        "actual_amount_minor": actual,
        "difference_minor": difference,
        "severity": "high" if abs(difference) > 1 else "medium",
        "occurred_at": occurred,
    }


def _transaction_issue(row, expected):
    return _base(
        "transaction_identity",
        "transaction",
        row.id,
        row.platform_transaction_id or row.source_record_key,
        row.currency,
        expected,
        row.settlement_amount_minor,
        row.occurred_at,
    )


def _missing_order_issue(row):
    item = _base(
        "missing_order",
        "transaction",
        row.id,
        row.platform_order_id or row.source_record_key,
        row.currency,
        row.settlement_amount_minor,
        row.settlement_amount_minor,
        row.occurred_at,
    )
    item["severity"] = "medium"
    return item


def _statement_issue(row):
    item = row[0]
    return _base(
        "statement_transaction",
        "statement",
        item.id,
        item.platform_statement_id,
        item.currency,
        int(row.expected),
        item.settlement_amount_minor,
        item.statement_end_at,
    )


def _payment_issue(row):
    item = row[0]
    kind = "orphan_payment" if int(row.linked_count) == 0 else "payment_statement"
    return _base(
        kind,
        "payment",
        item.id,
        item.platform_payment_id,
        item.currency,
        int(row.expected),
        item.payment_amount_minor,
        item.paid_at or item.initiated_at,
    )
