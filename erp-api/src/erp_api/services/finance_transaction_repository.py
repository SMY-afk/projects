from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, select

from erp_api.models.finance_statement import FinanceStatement
from erp_api.models.finance_transaction import FinanceTransaction
from erp_api.models.finance_transaction_component import FinanceTransactionComponent
from erp_api.models.order import Order
from erp_api.services.finance_repository_queries import transaction_filters


async def load_transaction_page(database, tenant_id, *, page, page_size, query):
    filters = transaction_filters(query)
    async for session in database.session(tenant_id):
        rows = await session.execute(
            _transaction_select()
            .where(*filters)
            .order_by(FinanceTransaction.occurred_at.desc(), FinanceTransaction.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = await _rows_with_components(session, rows.all())
        total = await session.scalar(
            select(func.count()).select_from(FinanceTransaction).where(*filters)
        )
        return items, total or 0
    raise RuntimeError("Tenant database session was not created.")


async def load_transaction(database, tenant_id, transaction_id):
    async for session in database.session(tenant_id):
        rows = await session.execute(
            _transaction_select().where(FinanceTransaction.id == transaction_id)
        )
        items = await _rows_with_components(session, rows.all())
        return items[0] if items else None
    return None


async def load_transactions_for_statement(session, statement_id):
    rows = await session.execute(
        _transaction_select()
        .where(FinanceTransaction.statement_id == statement_id)
        .order_by(FinanceTransaction.occurred_at.desc(), FinanceTransaction.id)
    )
    return await _rows_with_components(session, rows.all())


async def load_order_summary(database, tenant_id: UUID, order_id: UUID):
    async for session in database.session(tenant_id):
        order = await session.scalar(select(Order).where(Order.id == order_id))
        if order is None:
            return None
        rows = await session.execute(
            _transaction_select()
            .where(FinanceTransaction.order_id == order_id)
            .order_by(FinanceTransaction.occurred_at.desc(), FinanceTransaction.id)
        )
        transactions = await _rows_with_components(session, rows.all())
        totals: dict[str, dict[str, int]] = {}
        for item in transactions:
            transaction = item["transaction"]
            currency = transaction.currency
            total = totals.setdefault(
                currency,
                {
                    "transaction_count": 0,
                    "revenue_amount_minor": 0,
                    "fee_amount_minor": 0,
                    "settlement_amount_minor": 0,
                },
            )
            total["transaction_count"] += 1
            total["revenue_amount_minor"] += transaction.revenue_amount_minor
            total["fee_amount_minor"] += transaction.fee_amount_minor
            total["settlement_amount_minor"] += transaction.settlement_amount_minor
        return {"order": order, "totals": totals, "transactions": transactions}
    return None


def _transaction_select():
    transaction = FinanceTransaction
    return (
        select(
            transaction,
            Order.order_number,
            FinanceStatement.platform_statement_id,
        )
        .outerjoin(
            Order,
            and_(
                Order.id == transaction.order_id,
                Order.tenant_id == transaction.tenant_id,
            ),
        )
        .outerjoin(
            FinanceStatement,
            and_(
                FinanceStatement.id == transaction.statement_id,
                FinanceStatement.tenant_id == transaction.tenant_id,
            ),
        )
    )


async def _rows_with_components(session, rows) -> list[dict[str, Any]]:
    transaction_ids = [row[0].id for row in rows]
    components: dict[UUID, list[FinanceTransactionComponent]] = {
        item_id: [] for item_id in transaction_ids
    }
    if transaction_ids:
        result = await session.scalars(
            select(FinanceTransactionComponent)
            .where(FinanceTransactionComponent.transaction_id.in_(transaction_ids))
            .order_by(
                FinanceTransactionComponent.transaction_id,
                FinanceTransactionComponent.component_category,
                FinanceTransactionComponent.component_code,
            )
        )
        for component in result:
            components[component.transaction_id].append(component)
    return [
        {
            "transaction": row[0],
            "order_number": row[1],
            "platform_statement_id": row[2],
            "components": components[row[0].id],
        }
        for row in rows
    ]
