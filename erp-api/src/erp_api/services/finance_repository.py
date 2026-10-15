from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, select

from erp_api.infrastructure.database import Database
from erp_api.models.finance_payment import FinancePayment, FinancePaymentStatement
from erp_api.models.finance_statement import FinanceStatement
from erp_api.services.finance_export_repository import stream_finance_export
from erp_api.services.finance_overview_repository import load_finance_overview
from erp_api.services.finance_reconciliation_repository import load_reconciliation
from erp_api.services.finance_repository_queries import (
    payment_filters,
    payment_statement_totals,
    statement_filters,
    statement_payment_totals,
    statement_transaction_totals,
)
from erp_api.services.finance_transaction_repository import (
    load_order_summary,
    load_transaction,
    load_transaction_page,
    load_transactions_for_statement,
)


@dataclass(frozen=True)
class FinanceQuery:
    shop_id: UUID | None = None
    currency: str | None = None
    status: str | None = None
    window_from: datetime | None = None
    window_to: datetime | None = None
    statement_id: UUID | None = None
    order_id: UUID | None = None
    transaction_type: str | None = None
    is_estimated: bool | None = None
    keyword: str | None = None
    payment_status: str | None = None
    payment_state: str | None = None


@dataclass(frozen=True)
class FinancePage:
    items: list[dict[str, Any]]
    total: int


class FinanceRepository:
    def __init__(self, database: Database, *, export_max_rows: int = 100_000) -> None:
        self._database = database
        self._export_max_rows = export_max_rows

    async def overview(self, tenant_id: UUID, *, query: FinanceQuery):
        return await load_finance_overview(self._database, tenant_id, query)

    async def list_statements(
        self, tenant_id: UUID, *, page: int, page_size: int, query: FinanceQuery
    ) -> FinancePage:
        filters = statement_filters(query)
        async for session in self._database.session(tenant_id):
            rows = await session.execute(
                _statement_select()
                .where(*filters)
                .order_by(FinanceStatement.statement_end_at.desc(), FinanceStatement.id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            total = await session.scalar(
                select(func.count()).select_from(FinanceStatement).where(*filters)
            )
            return FinancePage([_statement_row(row) for row in rows], total or 0)
        raise RuntimeError("Tenant database session was not created.")

    async def get_statement(self, tenant_id: UUID, statement_id: UUID):
        async for session in self._database.session(tenant_id):
            result = await session.execute(
                _statement_select().where(FinanceStatement.id == statement_id)
            )
            row = result.first()
            if row is None:
                return None
            item = _statement_row(row)
            item["transactions"] = await load_transactions_for_statement(
                session, statement_id
            )
            payments = await session.scalars(
                select(FinancePayment)
                .join(
                    FinancePaymentStatement,
                    and_(
                        FinancePaymentStatement.payment_id == FinancePayment.id,
                        FinancePaymentStatement.tenant_id == FinancePayment.tenant_id,
                    ),
                )
                .where(FinancePaymentStatement.statement_id == statement_id)
                .order_by(FinancePayment.initiated_at.desc())
            )
            item["payments"] = list(payments.all())
            return item
        return None

    async def list_transactions(
        self, tenant_id: UUID, *, page: int, page_size: int, query: FinanceQuery
    ) -> FinancePage:
        items, total = await load_transaction_page(
            self._database, tenant_id, page=page, page_size=page_size, query=query
        )
        return FinancePage(items, total)

    async def get_transaction(self, tenant_id: UUID, transaction_id: UUID):
        return await load_transaction(self._database, tenant_id, transaction_id)

    async def list_payments(
        self, tenant_id: UUID, *, page: int, page_size: int, query: FinanceQuery
    ) -> FinancePage:
        filters = payment_filters(query)
        async for session in self._database.session(tenant_id):
            rows = await session.execute(
                _payment_select()
                .where(*filters)
                .order_by(FinancePayment.initiated_at.desc(), FinancePayment.id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            total = await session.scalar(
                select(func.count()).select_from(FinancePayment).where(*filters)
            )
            return FinancePage([_payment_row(row) for row in rows], total or 0)
        raise RuntimeError("Tenant database session was not created.")

    async def reconciliation(self, tenant_id: UUID, *, query: FinanceQuery):
        return await load_reconciliation(self._database, tenant_id, query)

    async def order_summary(self, tenant_id: UUID, order_id: UUID):
        return await load_order_summary(self._database, tenant_id, order_id)

    def stream_export(
        self, tenant_id: UUID, *, resource: str, query: FinanceQuery
    ) -> AsyncIterator[str]:
        return stream_finance_export(
            self._database,
            tenant_id,
            resource=resource,
            query=query,
            max_rows=self._export_max_rows,
        )


def _statement_select():
    transactions = statement_transaction_totals()
    payments = statement_payment_totals()
    return (
        select(
            FinanceStatement,
            func.coalesce(transactions.c.transaction_count, 0),
            func.coalesce(transactions.c.transaction_amount_minor, 0),
            func.coalesce(payments.c.payment_count, 0),
            func.coalesce(payments.c.payment_amount_minor, 0),
        )
        .outerjoin(transactions, transactions.c.statement_id == FinanceStatement.id)
        .outerjoin(payments, payments.c.statement_id == FinanceStatement.id)
    )


def _payment_select():
    statements = payment_statement_totals()
    return select(
        FinancePayment,
        func.coalesce(statements.c.statement_count, 0),
        func.coalesce(statements.c.statement_amount_minor, 0),
    ).outerjoin(statements, statements.c.payment_id == FinancePayment.id)


def _statement_row(row) -> dict[str, Any]:
    return {
        "statement": row[0],
        "transaction_count": int(row[1]),
        "transaction_amount_minor": int(row[2]),
        "payment_count": int(row[3]),
        "payment_amount_minor": int(row[4]),
    }


def _payment_row(row) -> dict[str, Any]:
    return {
        "payment": row[0],
        "statement_count": int(row[1]),
        "statement_amount_minor": int(row[2]),
    }
