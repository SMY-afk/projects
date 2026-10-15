from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select, text, update
from sqlalchemy.dialects.postgresql import insert

from erp_api.infrastructure.database import Database
from erp_api.models.finance_payment import FinancePayment
from erp_api.models.finance_statement import FinanceStatement
from erp_api.models.finance_sync import FinanceSyncCursor, FinanceSyncRun
from erp_api.models.finance_transaction import FinanceTransaction
from erp_api.models.finance_transaction_component import FinanceTransactionComponent
from erp_api.models.order import Order
from erp_api.services.finance_sync_mapping import (
    component_values,
    payment_values,
    settled_transaction_values,
    statement_values,
    unsettled_transaction_values,
)


def transaction_upsert_statement(values: list[dict[str, Any]]):
    statement = insert(FinanceTransaction).values(values)
    excluded = statement.excluded
    immutable = {"id", "tenant_id", "shop_id", "source_record_key"}
    updates = {
        column.name: getattr(excluded, column.name)
        for column in FinanceTransaction.__table__.columns
        if column.name not in immutable
    }
    return statement.on_conflict_do_update(
        constraint="uq_finance_transactions_tenant_shop_source",
        set_=updates,
        where=text(
            "finance_transactions.is_estimated = true OR excluded.is_estimated = false"
        ),
    )


class FinanceSyncPageRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def upsert_statements_page(
        self, tenant_id, run_id, shop_id, *, page, recovery_cursor
    ) -> int:
        now = datetime.now(UTC)
        values = [
            statement_values(tenant_id, shop_id, item, now) for item in page.statements
        ]
        async for session in self._database.session(tenant_id):
            if values:
                statement = insert(FinanceStatement).values(values)
                excluded = statement.excluded
                await session.execute(
                    statement.on_conflict_do_update(
                        constraint="uq_finance_statements_tenant_shop_platform",
                        set_={
                            key: getattr(excluded, key)
                            for key in values[0]
                            if key
                            not in {
                                "tenant_id",
                                "shop_id",
                                "platform_statement_id",
                            }
                        },
                    )
                )
            await _checkpoint(
                session,
                tenant_id,
                run_id,
                shop_id,
                "statements",
                recovery_cursor,
                len(values),
            )
            await session.commit()
            return len(values)
        raise RuntimeError("Tenant database session was not created.")

    async def upsert_payments_page(
        self, tenant_id, run_id, shop_id, *, page, recovery_cursor
    ) -> int:
        now = datetime.now(UTC)
        values = [
            payment_values(tenant_id, shop_id, item, now) for item in page.payments
        ]
        async for session in self._database.session(tenant_id):
            if values:
                statement = insert(FinancePayment).values(values)
                excluded = statement.excluded
                await session.execute(
                    statement.on_conflict_do_update(
                        constraint="uq_finance_payments_tenant_shop_platform",
                        set_={
                            key: getattr(excluded, key)
                            for key in values[0]
                            if key
                            not in {"tenant_id", "shop_id", "platform_payment_id"}
                        },
                    )
                )
            await _checkpoint(
                session,
                tenant_id,
                run_id,
                shop_id,
                "payments",
                recovery_cursor,
                len(values),
            )
            await session.commit()
            return len(values)
        raise RuntimeError("Tenant database session was not created.")

    async def upsert_unsettled_page(
        self, tenant_id, run_id, shop_id, *, page, recovery_cursor
    ) -> int:
        now = datetime.now(UTC)
        async for session in self._database.session(tenant_id):
            order_ids = await _order_ids(
                session, shop_id, [item.order_id for item in page.transactions]
            )
            values = [
                unsettled_transaction_values(
                    tenant_id,
                    shop_id,
                    item,
                    order_ids.get(item.order_id),
                    now,
                )
                for item in page.transactions
            ]
            if values:
                await session.execute(transaction_upsert_statement(values))
            await _checkpoint(
                session,
                tenant_id,
                run_id,
                shop_id,
                "unsettled",
                recovery_cursor,
                len(values),
            )
            await session.commit()
            return len(values)
        raise RuntimeError("Tenant database session was not created.")

    async def upsert_statement_transactions_page(
        self,
        tenant_id,
        run_id,
        shop_id,
        *,
        statement_platform_id,
        page,
        order_details,
        recovery_cursor,
    ) -> int:
        now = datetime.now(UTC)
        async for session in self._database.session(tenant_id):
            stored_statement = await session.scalar(
                select(FinanceStatement).where(
                    FinanceStatement.shop_id == shop_id,
                    FinanceStatement.platform_statement_id == statement_platform_id,
                )
            )
            if stored_statement is None:
                raise RuntimeError("Finance statement dependency was not found.")
            order_ids = await _order_ids(
                session,
                shop_id,
                [item.order_id for item in page.transactions if item.order_id],
            )
            for item in page.transactions:
                value = settled_transaction_values(
                    tenant_id,
                    shop_id,
                    stored_statement.id,
                    item,
                    page.currency,
                    order_ids.get(item.order_id),
                    now,
                )
                transaction_id = (
                    await session.execute(
                        transaction_upsert_statement([value]).returning(
                            FinanceTransaction.id
                        )
                    )
                ).scalar_one()
                await session.execute(
                    delete(FinanceTransactionComponent).where(
                        FinanceTransactionComponent.transaction_id == transaction_id
                    )
                )
                components = component_values(
                    tenant_id,
                    transaction_id,
                    item,
                    page.currency,
                    order_details.get(item.order_id),
                )
                if components:
                    await session.execute(
                        insert(FinanceTransactionComponent).values(components)
                    )
            count = len(page.transactions)
            await _checkpoint(
                session,
                tenant_id,
                run_id,
                shop_id,
                "statement_transactions",
                recovery_cursor,
                count,
            )
            await session.commit()
            return count
        raise RuntimeError("Tenant database session was not created.")

    async def list_statements_in_window(
        self, tenant_id, shop_id, *, window_from, window_to
    ) -> list[FinanceStatement]:
        async for session in self._database.session(tenant_id):
            return list(
                await session.scalars(
                    select(FinanceStatement)
                    .where(
                        FinanceStatement.shop_id == shop_id,
                        FinanceStatement.statement_end_at >= window_from,
                        FinanceStatement.statement_end_at < window_to,
                    )
                    .order_by(
                        FinanceStatement.statement_end_at,
                        FinanceStatement.id,
                    )
                )
            )
        raise RuntimeError("Tenant database session was not created.")


async def _checkpoint(
    session, tenant_id, run_id, shop_id, entity_type, recovery_cursor, count
):
    cursor = await _cursor(session, tenant_id, shop_id, entity_type)
    cursor.recovery_cursor = recovery_cursor
    await session.execute(
        update(FinanceSyncRun)
        .where(FinanceSyncRun.id == run_id)
        .values(
            recovery_cursor=recovery_cursor,
            fetched_count=FinanceSyncRun.fetched_count + count,
            written_count=FinanceSyncRun.written_count + count,
        )
    )


async def _cursor(session, tenant_id, shop_id, entity_type):
    cursor = await session.scalar(
        select(FinanceSyncCursor).where(
            FinanceSyncCursor.shop_id == shop_id,
            FinanceSyncCursor.entity_type == entity_type,
        )
    )
    if cursor is None:
        cursor = FinanceSyncCursor(
            tenant_id=tenant_id,
            shop_id=shop_id,
            entity_type=entity_type,
        )
        session.add(cursor)
    return cursor


async def _order_ids(session, shop_id, platform_ids):
    ids = [value for value in platform_ids if value]
    if not ids:
        return {}
    rows = (
        await session.execute(
            select(Order.platform_order_id, Order.id).where(
                Order.shop_id == shop_id,
                Order.platform_order_id.in_(ids),
            )
        )
    ).all()
    return dict(rows)
