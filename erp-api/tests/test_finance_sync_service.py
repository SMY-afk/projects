from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from erp_api.services.finance_sync_repository import (
    FinanceStoredCursor,
    FinanceSyncResult,
)
from erp_api.services.finance_sync_service import (
    FinanceSyncService,
    FinanceSyncWindowError,
)


class FakeShopRepository:
    async def get_authorized_tiktok_shop(self, tenant_id, shop_id):
        return {"id": shop_id}

    async def get_access_token(self, tenant_id, shop_id):
        return "access-token"

    async def get_shop_cipher(self, tenant_id, shop_id):
        return "shop-cipher"


class FakeRepository:
    def __init__(self, cursors=None, fail_status="retry_wait") -> None:
        self.cursors = cursors or {}
        self.fail_status = fail_status
        self.events = []
        self.completed = False
        self.failed = False
        self.statements = [SimpleNamespace(platform_statement_id="statement-1")]

    async def get_cursor(self, tenant_id, shop_id, entity_type):
        return self.cursors.get(entity_type, FinanceStoredCursor(None, None, None))

    async def create_run(self, tenant_id, shop_id, **kwargs):
        self.events.append(("create_run", kwargs["mode"]))
        return uuid4()

    async def upsert_unsettled_page(self, *args, page, recovery_cursor, **kwargs):
        self.events.append(("unsettled", recovery_cursor))
        return len(page.transactions)

    async def upsert_statements_page(self, *args, page, recovery_cursor, **kwargs):
        self.events.append(("statements", recovery_cursor))
        return len(page.statements)

    async def list_statements_in_window(self, *args, **kwargs):
        return self.statements

    async def upsert_statement_transactions_page(
        self, *args, page, order_details, recovery_cursor, **kwargs
    ):
        self.events.append(
            ("statement_transactions", recovery_cursor, len(order_details))
        )
        return len(page.transactions)

    async def upsert_payments_page(self, *args, page, recovery_cursor, **kwargs):
        self.events.append(("payments", recovery_cursor))
        return len(page.payments)

    async def complete_run(self, tenant_id, run_id, **kwargs):
        self.completed = True
        return FinanceSyncResult(run_id, kwargs["shop_id"], "succeeded", 4, 4)

    async def fail_run(self, tenant_id, run_id, **kwargs):
        self.failed = True
        self.fail_call = kwargs
        return FinanceSyncResult(
            run_id, kwargs["shop_id"], self.fail_status, 0, 0, error="safe"
        )


class FakeFinanceClient:
    def __init__(self, *, fail_on=None) -> None:
        self.fail_on = fail_on
        self.calls = []

    async def list_unsettled_transactions(self, *args, page_token=None, **kwargs):
        self._record("unsettled", page_token)
        return SimpleNamespace(
            transactions=[SimpleNamespace(id="transaction-1")],
            next_page_token="",
        )

    async def list_statements(self, *args, page_token=None, **kwargs):
        self._record("statements", page_token)
        return SimpleNamespace(
            statements=[SimpleNamespace(id="statement-1")],
            next_page_token="",
        )

    async def list_statement_transactions(
        self, *args, statement_id, page_token=None, **kwargs
    ):
        self._record("statement_transactions", page_token)
        return SimpleNamespace(
            statement_id=statement_id,
            transactions=[SimpleNamespace(order_id="order-1")],
            next_page_token="",
        )

    async def get_order_transactions(self, *args, order_id, **kwargs):
        self._record("order_transactions", order_id)
        return SimpleNamespace(order_id=order_id, sku_transactions=[])

    async def list_payments(self, *args, page_token=None, **kwargs):
        self._record("payments", page_token)
        return SimpleNamespace(
            payments=[SimpleNamespace(id="payment-1")],
            next_page_token="",
        )

    def _record(self, name, value) -> None:
        self.calls.append((name, value))
        if self.fail_on == name:
            raise RuntimeError(f"{name} failed")


class ConcurrentFinanceClient(FakeFinanceClient):
    def __init__(self) -> None:
        super().__init__()
        self.active = 0
        self.max_active = 0

    async def list_statement_transactions(
        self, *args, statement_id, page_token=None, **kwargs
    ):
        self._record("statement_transactions", page_token)
        return SimpleNamespace(
            statement_id=statement_id,
            transactions=[
                SimpleNamespace(order_id=f"order-{index}") for index in range(6)
            ],
            next_page_token="",
        )

    async def get_order_transactions(self, *args, order_id, **kwargs):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0.01)
        self.active -= 1
        return SimpleNamespace(order_id=order_id, sku_transactions=[])


class PaginatedFinanceClient(FakeFinanceClient):
    async def list_statement_transactions(
        self, *args, statement_id, page_token=None, **kwargs
    ):
        self._record("statement_transactions", page_token)
        return SimpleNamespace(
            statement_id=statement_id,
            transactions=[SimpleNamespace(order_id="order-1")],
            next_page_token="page-2" if page_token is None else "",
        )


def _service(repository, client, *, clock=None) -> FinanceSyncService:
    return FinanceSyncService(
        repository,
        FakeShopRepository(),
        client,
        initial_sync_days=30,
        incremental_overlap_hours=24,
        clock=clock or (lambda: datetime(2026, 8, 21, tzinfo=UTC)),
    )


def test_backfill_requires_an_explicit_bounded_window() -> None:
    service = _service(FakeRepository(), FakeFinanceClient())

    with pytest.raises(FinanceSyncWindowError, match="requires both"):
        asyncio.run(service.sync(uuid4(), shop_id=uuid4(), mode="backfill"))
    with pytest.raises(FinanceSyncWindowError, match="cannot exceed 30 days"):
        asyncio.run(
            service.sync(
                uuid4(),
                shop_id=uuid4(),
                mode="backfill",
                window_from=datetime(2026, 7, 1, tzinfo=UTC),
                window_to=datetime(2026, 8, 2, tzinfo=UTC),
            )
        )


def test_sync_preserves_statement_transaction_payment_dependency_order() -> None:
    repository = FakeRepository()
    client = FakeFinanceClient()

    result = asyncio.run(
        _service(repository, client).sync(
            uuid4(),
            shop_id=uuid4(),
            mode="backfill",
            window_from=datetime(2026, 7, 22, tzinfo=UTC),
            window_to=datetime(2026, 8, 21, tzinfo=UTC),
        )
    )

    assert result.status == "succeeded"
    names = [name for name, _ in client.calls]
    assert names.index("statements") < names.index("statement_transactions")
    assert names.index("statement_transactions") < names.index("payments")
    assert "order_transactions" in names
    assert repository.completed is True


def test_statement_transactions_follow_second_page() -> None:
    repository = FakeRepository()
    client = PaginatedFinanceClient()

    result = asyncio.run(
        _service(repository, client).sync(
            uuid4(),
            shop_id=uuid4(),
            mode="backfill",
            window_from=datetime(2026, 7, 22, tzinfo=UTC),
            window_to=datetime(2026, 8, 21, tzinfo=UTC),
        )
    )

    assert result.status == "succeeded"
    assert [token for name, token in client.calls if name == "statement_transactions"] == [
        None, "page-2"
    ]


def test_failed_page_resumes_from_recovery_without_committing_cursor() -> None:
    recovery = json.dumps(
        {
            "window_from": "2026-07-22T00:00:00+00:00",
            "window_to": "2026-08-21T00:00:00+00:00",
            "page_token": "resume-token",
        },
        sort_keys=True,
    )
    repository = FakeRepository(
        {"statements": FinanceStoredCursor(recovery, "old-commit", None)}
    )
    client = FakeFinanceClient(fail_on="payments")

    result = asyncio.run(
        _service(repository, client).sync(
            uuid4(),
            shop_id=uuid4(),
            mode="backfill",
            window_from=datetime(2026, 7, 22, tzinfo=UTC),
            window_to=datetime(2026, 8, 21, tzinfo=UTC),
            attempt=1,
            max_attempts=5,
        )
    )

    assert ("statements", "resume-token") in client.calls
    assert result.status == "retry_wait"
    assert repository.failed is True
    assert repository.completed is False


def test_incremental_window_rolls_from_last_success_with_overlap() -> None:
    repository = FakeRepository(
        {
            "finance": FinanceStoredCursor(
                None,
                "2026-08-20T12:00:00+00:00",
                datetime(2026, 8, 20, 12, tzinfo=UTC),
            )
        }
    )
    service = _service(repository, FakeFinanceClient())

    start, end = asyncio.run(service.resolve_window(uuid4(), uuid4(), "incremental"))

    assert start == datetime(2026, 8, 19, 12, tzinfo=UTC)
    assert end == datetime(2026, 8, 21, tzinfo=UTC)


def test_initial_incremental_window_is_stable_and_bounded() -> None:
    service = _service(
        FakeRepository(),
        FakeFinanceClient(),
        clock=lambda: datetime(2026, 8, 21, 12, tzinfo=UTC),
    )

    start, end = asyncio.run(service.resolve_window(uuid4(), uuid4(), "incremental"))

    assert start == datetime(2026, 7, 22, tzinfo=UTC)
    assert end == datetime(2026, 7, 25, tzinfo=UTC)


def test_incremental_backlog_advances_with_one_day_overlap() -> None:
    repository = FakeRepository(
        {
            "finance": FinanceStoredCursor(
                None,
                "2026-08-01T00:00:00+00:00",
                datetime(2026, 8, 1, tzinfo=UTC),
            )
        }
    )
    service = _service(repository, FakeFinanceClient())

    start, end = asyncio.run(service.resolve_window(uuid4(), uuid4(), "incremental"))

    assert start == datetime(2026, 7, 31, tzinfo=UTC)
    assert end == datetime(2026, 8, 3, tzinfo=UTC)


def test_last_attempt_becomes_observable_dead_letter() -> None:
    repository = FakeRepository(fail_status="dead_letter")

    result = asyncio.run(
        _service(repository, FakeFinanceClient(fail_on="statements")).sync(
            uuid4(), shop_id=uuid4(), attempt=5, max_attempts=5
        )
    )

    assert result.status == "dead_letter"


def test_order_transaction_enrichment_uses_bounded_concurrency() -> None:
    client = ConcurrentFinanceClient()
    service = FinanceSyncService(
        FakeRepository(),
        FakeShopRepository(),
        client,
        initial_sync_days=30,
        incremental_overlap_hours=24,
        order_detail_concurrency=2,
        clock=lambda: datetime(2026, 8, 21, tzinfo=UTC),
    )

    result = asyncio.run(
        service.sync(
            uuid4(),
            shop_id=uuid4(),
            mode="backfill",
            window_from=datetime(2026, 7, 22, tzinfo=UTC),
            window_to=datetime(2026, 8, 21, tzinfo=UTC),
        )
    )

    assert result.status == "succeeded"
    assert client.max_active == 2


def test_cancelled_finance_sync_is_audited_and_propagated() -> None:
    class CancelledClient(FakeFinanceClient):
        async def get_order_transactions(self, *args, **kwargs):
            raise asyncio.CancelledError

    repository = FakeRepository()
    service = _service(repository, CancelledClient())

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(service.sync(uuid4(), shop_id=uuid4()))

    assert repository.failed is True
    assert repository.fail_call["status"] == "cancelled"
    assert repository.fail_call["error"] == "Finance sync interrupted."
    assert repository.completed is False
