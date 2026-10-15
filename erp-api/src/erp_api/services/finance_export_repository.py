from __future__ import annotations

from uuid import UUID

from sqlalchemy import and_, select

from erp_api.models.finance_payment import FinancePayment
from erp_api.models.finance_statement import FinanceStatement
from erp_api.models.finance_transaction import FinanceTransaction
from erp_api.models.order import Order
from erp_api.services.finance_export import csv_row
from erp_api.services.finance_repository_queries import (
    payment_filters,
    statement_filters,
    transaction_filters,
)

_HEADERS = {
    "transactions": (
        "transactionId",
        "platformTransactionId",
        "orderId",
        "orderNumber",
        "platformOrderId",
        "type",
        "status",
        "basis",
        "currency",
        "revenueAmountMinor",
        "refundAmountMinor",
        "shippingAmountMinor",
        "feeAmountMinor",
        "adjustmentAmountMinor",
        "settlementAmountMinor",
        "occurredAt",
    ),
    "statements": (
        "statementId",
        "platformStatementId",
        "status",
        "paymentStatus",
        "currency",
        "revenueAmountMinor",
        "feeAmountMinor",
        "adjustmentAmountMinor",
        "settlementAmountMinor",
        "statementStartAt",
        "statementEndAt",
    ),
    "payments": (
        "paymentId",
        "platformPaymentId",
        "status",
        "currency",
        "paymentAmountMinor",
        "initiatedAt",
        "paidAt",
        "bankReferenceMasked",
    ),
}


async def stream_finance_export(
    database,
    tenant_id: UUID,
    *,
    resource: str,
    query,
    max_rows: int,
):
    yield "\ufeff" + csv_row(_HEADERS[resource])
    async for session in database.session(tenant_id):
        statement = _export_select(resource, query).limit(max_rows)
        result = await session.stream(statement.execution_options(yield_per=500))
        async for row in result:
            yield csv_row(_values(resource, row))
        return


def _export_select(resource: str, query):
    if resource == "transactions":
        transaction = FinanceTransaction
        return (
            select(transaction, Order.order_number)
            .outerjoin(
                Order,
                and_(
                    Order.id == transaction.order_id,
                    Order.tenant_id == transaction.tenant_id,
                ),
            )
            .where(*transaction_filters(query))
            .order_by(transaction.occurred_at.desc(), transaction.id)
        )
    if resource == "statements":
        return (
            select(FinanceStatement)
            .where(*statement_filters(query))
            .order_by(FinanceStatement.statement_end_at.desc(), FinanceStatement.id)
        )
    return (
        select(FinancePayment)
        .where(*payment_filters(query))
        .order_by(FinancePayment.initiated_at.desc(), FinancePayment.id)
    )


def _values(resource: str, row):
    item = row[0]
    if resource == "transactions":
        return (
            item.id,
            item.platform_transaction_id or "",
            item.order_id or "",
            row[1] or "",
            item.platform_order_id or "",
            item.transaction_type,
            item.status,
            "estimated" if item.is_estimated else "settled",
            item.currency,
            item.revenue_amount_minor,
            item.refund_amount_minor,
            item.shipping_amount_minor,
            item.fee_amount_minor,
            item.adjustment_amount_minor,
            item.settlement_amount_minor,
            item.occurred_at.isoformat(),
        )
    if resource == "statements":
        return (
            item.id,
            item.platform_statement_id,
            item.status,
            item.payment_status,
            item.currency,
            item.revenue_amount_minor,
            item.fee_amount_minor,
            item.adjustment_amount_minor,
            item.settlement_amount_minor,
            item.statement_start_at.isoformat(),
            item.statement_end_at.isoformat(),
        )
    return (
        item.id,
        item.platform_payment_id,
        item.status,
        item.currency,
        item.payment_amount_minor,
        item.initiated_at.isoformat(),
        item.paid_at.isoformat() if item.paid_at else "",
        item.bank_reference_masked or "",
    )
