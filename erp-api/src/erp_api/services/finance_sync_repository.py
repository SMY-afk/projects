from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select

from erp_api.infrastructure.database import Database
from erp_api.models.finance_sync import FinanceSyncCursor, FinanceSyncRun
from erp_api.services.finance_sync_mapping import minor_units
from erp_api.services.finance_sync_page_repository import (
    FinanceSyncPageRepository,
    transaction_upsert_statement,
)

_CURSOR_TYPES = (
    "finance",
    "unsettled",
    "statements",
    "statement_transactions",
    "payments",
)


@dataclass(frozen=True)
class FinanceStoredCursor:
    recovery_cursor: str | None
    committed_cursor: str | None
    last_successful_at: datetime | None


@dataclass(frozen=True)
class FinanceSyncResult:
    run_id: UUID
    shop_id: UUID
    status: str
    fetched_count: int
    written_count: int
    recovery_cursor: str | None = None
    error: str | None = None


def _minor_units(value: Decimal, currency: str) -> int:
    return minor_units(value, currency)


_transaction_upsert_statement = transaction_upsert_statement


class FinanceSyncRepository:
    def __init__(self, database: Database) -> None:
        self._database = database
        self._pages = FinanceSyncPageRepository(database)

    async def get_cursor(
        self, tenant_id: UUID, shop_id: UUID, entity_type: str
    ) -> FinanceStoredCursor:
        async for session in self._database.session(tenant_id):
            row = await session.scalar(
                select(FinanceSyncCursor).where(
                    FinanceSyncCursor.shop_id == shop_id,
                    FinanceSyncCursor.entity_type == entity_type,
                )
            )
            if row is None:
                return FinanceStoredCursor(None, None, None)
            return FinanceStoredCursor(
                row.recovery_cursor,
                row.committed_cursor,
                row.last_successful_at,
            )
        raise RuntimeError("Tenant database session was not created.")

    async def create_run(
        self,
        tenant_id: UUID,
        shop_id: UUID,
        *,
        mode: str,
        window_from: datetime,
        window_to: datetime,
        trigger: str = "manual",
    ) -> UUID:
        del trigger
        async for session in self._database.session(tenant_id):
            run = FinanceSyncRun(
                tenant_id=tenant_id,
                shop_id=shop_id,
                entity_type="finance",
                mode=mode,
                status="running",
                window_from=window_from,
                window_to=window_to,
            )
            session.add(run)
            await session.commit()
            return run.id
        raise RuntimeError("Tenant database session was not created.")

    async def upsert_statements_page(self, *args, **kwargs) -> int:
        return await self._pages.upsert_statements_page(*args, **kwargs)

    async def upsert_payments_page(self, *args, **kwargs) -> int:
        return await self._pages.upsert_payments_page(*args, **kwargs)

    async def upsert_unsettled_page(self, *args, **kwargs) -> int:
        return await self._pages.upsert_unsettled_page(*args, **kwargs)

    async def upsert_statement_transactions_page(self, *args, **kwargs) -> int:
        return await self._pages.upsert_statement_transactions_page(*args, **kwargs)

    async def list_statements_in_window(self, *args, **kwargs):
        return await self._pages.list_statements_in_window(*args, **kwargs)

    async def complete_run(
        self,
        tenant_id: UUID,
        run_id: UUID,
        *,
        shop_id: UUID,
        committed_at: datetime,
    ) -> FinanceSyncResult:
        async for session in self._database.session(tenant_id):
            run = await session.get(FinanceSyncRun, run_id)
            if run is None:
                raise RuntimeError("Finance sync run was not found.")
            for entity_type in _CURSOR_TYPES:
                cursor = await _cursor(session, tenant_id, shop_id, entity_type)
                cursor.recovery_cursor = None
                cursor.committed_cursor = committed_at.isoformat()
                cursor.last_successful_at = committed_at
            run.status = "succeeded"
            run.recovery_cursor = None
            run.finished_at = datetime.now(UTC)
            await session.commit()
            return _result(run)
        raise RuntimeError("Tenant database session was not created.")

    async def fail_run(
        self,
        tenant_id: UUID,
        run_id: UUID,
        *,
        shop_id: UUID,
        error: str,
        status: str,
    ) -> FinanceSyncResult:
        del shop_id
        async for session in self._database.session(tenant_id):
            run = await session.get(FinanceSyncRun, run_id)
            if run is None:
                raise RuntimeError("Finance sync run was not found.")
            run.status = status
            run.failed_count += 1
            run.error_code = "finance_sync_failed"
            run.error_summary = error[:2000]
            run.finished_at = datetime.now(UTC)
            await session.commit()
            return _result(run)
        raise RuntimeError("Tenant database session was not created.")


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


def _result(run: FinanceSyncRun) -> FinanceSyncResult:
    return FinanceSyncResult(
        run.id,
        run.shop_id,
        run.status,
        run.fetched_count,
        run.written_count,
        run.recovery_cursor,
        run.error_summary,
    )
