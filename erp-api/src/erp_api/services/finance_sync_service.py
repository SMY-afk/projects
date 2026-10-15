from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

from erp_api.services.finance_sync_cursor import (
    cursor_state,
    next_token,
    resume,
    transaction_cursor,
    window_cursor,
)
from erp_api.services.finance_sync_repository import (
    FinanceSyncRepository,
    FinanceSyncResult,
)
from erp_api.services.finance_sync_safety import safe_error
from erp_api.services.tiktok_finance_client import TikTokFinanceClient
from erp_api.services.tiktok_transport import tiktok_request_context


class FinanceSyncWindowError(ValueError):
    """Raised when a Finance sync window is absent or unsafe."""


class FinanceSyncService:
    def __init__(
        self,
        repository: FinanceSyncRepository,
        shop_repository,
        client: TikTokFinanceClient,
        *,
        initial_sync_days: int = 30,
        incremental_overlap_hours: int = 24,
        order_detail_concurrency: int = 4,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._shop_repository = shop_repository
        self._client = client
        self._initial_sync_days = initial_sync_days
        self._incremental_overlap = timedelta(hours=incremental_overlap_hours)
        self._order_detail_concurrency = order_detail_concurrency
        self._clock = clock or (lambda: datetime.now(UTC))

    async def resolve_window(
        self,
        tenant_id: UUID,
        shop_id: UUID,
        mode: str,
        window_from: datetime | None = None,
        window_to: datetime | None = None,
    ) -> tuple[datetime, datetime]:
        if mode not in {"backfill", "incremental"}:
            raise FinanceSyncWindowError(
                "Finance mode must be backfill or incremental."
            )
        if (window_from is None) != (window_to is None):
            raise FinanceSyncWindowError(
                "Finance window requires both from and to values."
            )
        if mode == "backfill" and window_from is None:
            raise FinanceSyncWindowError(
                "Finance backfill requires both explicit window values."
            )
        if window_from is not None and window_to is not None:
            return self._validate_window(window_from, window_to)
        cursor = await self._repository.get_cursor(tenant_id, shop_id, "finance")
        end = self._utc_now()
        if cursor.last_successful_at is not None:
            start = cursor.last_successful_at - self._incremental_overlap
        else:
            start = (end - timedelta(days=self._initial_sync_days)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
        span = max(timedelta(days=3), self._incremental_overlap + timedelta(days=1))
        end = min(end, start + span)
        return self._validate_window(start, end)

    async def sync(
        self,
        tenant_id: UUID,
        *,
        shop_id: UUID,
        mode: str = "incremental",
        window_from: datetime | None = None,
        window_to: datetime | None = None,
        trigger: str = "manual",
        attempt: int = 1,
        max_attempts: int = 5,
    ) -> FinanceSyncResult:
        start, end = await self.resolve_window(
            tenant_id, shop_id, mode, window_from, window_to
        )
        await self._require_authorized_shop(tenant_id, shop_id)
        access_token = await self._shop_repository.get_access_token(tenant_id, shop_id)
        shop_cipher = await self._shop_repository.get_shop_cipher(tenant_id, shop_id)
        if not access_token or not shop_cipher:
            raise RuntimeError("TikTok Finance credentials are unavailable.")
        run_id = await self._repository.create_run(
            tenant_id,
            shop_id,
            mode=mode,
            window_from=start,
            window_to=end,
            trigger=trigger,
        )
        try:
            with tiktok_request_context(tenant_id=str(tenant_id), shop_id=str(shop_id)):
                await self._sync_unsettled(
                    tenant_id, run_id, shop_id, access_token, shop_cipher, start, end
                )
                await self._sync_statements(
                    tenant_id, run_id, shop_id, access_token, shop_cipher, start, end
                )
                await self._sync_statement_transactions(
                    tenant_id, run_id, shop_id, access_token, shop_cipher, start, end
                )
                await self._sync_payments(
                    tenant_id, run_id, shop_id, access_token, shop_cipher, start, end
                )
            return await self._repository.complete_run(
                tenant_id, run_id, shop_id=shop_id, committed_at=end
            )
        except asyncio.CancelledError:
            await self._repository.fail_run(
                tenant_id,
                run_id,
                shop_id=shop_id,
                status="cancelled",
                error="Finance sync interrupted.",
            )
            raise
        except Exception as error:  # noqa: BLE001 - every failed run must be audited
            status = "dead_letter" if attempt >= max_attempts else "retry_wait"
            return await self._repository.fail_run(
                tenant_id,
                run_id,
                shop_id=shop_id,
                status=status,
                error=safe_error(error),
            )

    async def _sync_unsettled(
        self, tenant_id, run_id, shop_id, token, cipher, start, end
    ):
        cursor = await self._repository.get_cursor(tenant_id, shop_id, "unsettled")
        page_token, done = resume(cursor, start, end)
        if done:
            return
        seen = set()
        while True:
            page = await self._client.list_unsettled_transactions(
                token,
                shop_cipher=cipher,
                from_time=start,
                to_time=end,
                page_token=page_token,
                page_size=100,
            )
            recovery = window_cursor(start, end, page.next_page_token)
            await self._repository.upsert_unsettled_page(
                tenant_id, run_id, shop_id, page=page, recovery_cursor=recovery
            )
            if not page.next_page_token:
                return
            page_token = next_token(page.next_page_token, seen)

    async def _sync_statements(
        self, tenant_id, run_id, shop_id, token, cipher, start, end
    ):
        cursor = await self._repository.get_cursor(tenant_id, shop_id, "statements")
        page_token, done = resume(cursor, start, end)
        if done:
            return
        seen = set()
        while True:
            page = await self._client.list_statements(
                token,
                shop_cipher=cipher,
                from_time=start,
                to_time=end,
                page_token=page_token,
                page_size=100,
            )
            recovery = window_cursor(start, end, page.next_page_token)
            await self._repository.upsert_statements_page(
                tenant_id, run_id, shop_id, page=page, recovery_cursor=recovery
            )
            if not page.next_page_token:
                return
            page_token = next_token(page.next_page_token, seen)

    async def _sync_statement_transactions(
        self, tenant_id, run_id, shop_id, token, cipher, start, end
    ):
        statements = await self._repository.list_statements_in_window(
            tenant_id, shop_id, window_from=start, window_to=end
        )
        cursor = await self._repository.get_cursor(
            tenant_id, shop_id, "statement_transactions"
        )
        state = cursor_state(cursor, start, end)
        if state.get("done"):
            return
        completed = state.get("completed_statement_id")
        page_token = state.get("page_token")
        resume_statement = state.get("statement_id") if page_token else None
        skipping = completed is not None or resume_statement is not None
        for index, statement in enumerate(statements):
            statement_id = statement.platform_statement_id
            if skipping:
                if completed and statement_id == completed:
                    skipping = False
                    continue
                if resume_statement and statement_id == resume_statement:
                    skipping = False
                else:
                    continue
            current_token = (
                page_token if state.get("statement_id") == statement_id else None
            )
            seen = set()
            while True:
                page = await self._client.list_statement_transactions(
                    token,
                    shop_cipher=cipher,
                    statement_id=statement_id,
                    page_token=current_token,
                    page_size=100,
                )
                details = await self._order_details(token, cipher, page.transactions)
                next_page_token = page.next_page_token
                recovery = transaction_cursor(
                    start,
                    end,
                    statement_id,
                    next_page_token,
                    done=not next_page_token and index == len(statements) - 1,
                )
                await self._repository.upsert_statement_transactions_page(
                    tenant_id,
                    run_id,
                    shop_id,
                    statement_platform_id=statement_id,
                    page=page,
                    order_details=details,
                    recovery_cursor=recovery,
                )
                if not next_page_token:
                    break
                current_token = next_token(next_page_token, seen)
            page_token = None

    async def _order_details(self, token, cipher, transactions):
        order_ids = tuple(
            dict.fromkeys(item.order_id for item in transactions if item.order_id)
        )
        semaphore = asyncio.Semaphore(self._order_detail_concurrency)

        async def fetch(order_id):
            async with semaphore:
                detail = await self._client.get_order_transactions(
                    token, shop_cipher=cipher, order_id=order_id
                )
                return order_id, detail

        return dict(await asyncio.gather(*(fetch(order_id) for order_id in order_ids)))

    async def _sync_payments(
        self, tenant_id, run_id, shop_id, token, cipher, start, end
    ):
        cursor = await self._repository.get_cursor(tenant_id, shop_id, "payments")
        page_token, done = resume(cursor, start, end)
        if done:
            return
        seen = set()
        while True:
            page = await self._client.list_payments(
                token,
                shop_cipher=cipher,
                from_time=start,
                to_time=end,
                page_token=page_token,
                page_size=100,
            )
            recovery = window_cursor(start, end, page.next_page_token)
            await self._repository.upsert_payments_page(
                tenant_id, run_id, shop_id, page=page, recovery_cursor=recovery
            )
            if not page.next_page_token:
                return
            page_token = next_token(page.next_page_token, seen)

    async def _require_authorized_shop(self, tenant_id, shop_id) -> None:
        shop = await self._shop_repository.get_authorized_tiktok_shop(
            tenant_id, shop_id
        )
        if shop is None:
            raise RuntimeError(
                "No authorized TikTok shop is available for this tenant."
            )

    def _validate_window(self, start: datetime, end: datetime):
        if any(
            value.tzinfo is None or value.utcoffset() is None for value in (start, end)
        ):
            raise FinanceSyncWindowError("Finance window must be timezone-aware.")
        start, end = start.astimezone(UTC), end.astimezone(UTC)
        if start >= end:
            raise FinanceSyncWindowError("Finance window must satisfy from < to.")
        if end - start > timedelta(days=self._initial_sync_days):
            raise FinanceSyncWindowError(
                f"Finance window cannot exceed {self._initial_sync_days} days."
            )
        return start, end

    def _utc_now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise FinanceSyncWindowError("Finance clock must be timezone-aware.")
        return value.astimezone(UTC)
