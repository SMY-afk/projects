import asyncio
from datetime import UTC, datetime
from uuid import uuid4

from erp_api.models.order_sync import OrderSyncCursor, OrderSyncRun
from erp_api.services.order_sync_repository import OrderSyncRepository
from erp_api.services.token_cipher import TokenCipher


class FakeDatabase:
    def __init__(self, session):
        self._session = session

    async def session(self, tenant_id):
        yield self._session


class FakeSession:
    def __init__(self, run, cursor):
        self.run = run
        self.cursor = cursor

    async def get(self, model, identity):
        return self.run

    async def scalar(self, statement):
        return self.cursor

    def add(self, value):
        self.cursor = value

    async def commit(self):
        return None


def test_older_backfill_does_not_regress_incremental_cursor() -> None:
    tenant_id, shop_id, run_id = uuid4(), uuid4(), uuid4()
    newer = datetime(2026, 8, 25, tzinfo=UTC)
    older = datetime(2025, 6, 1, tzinfo=UTC)
    run = OrderSyncRun(
        id=run_id,
        tenant_id=tenant_id,
        shop_id=shop_id,
        trigger="manual",
        mode="backfill",
        status="running",
        window_from=datetime(2025, 5, 1, tzinfo=UTC),
        window_to=older,
    )
    cursor = OrderSyncCursor(
        tenant_id=tenant_id,
        shop_id=shop_id,
        committed_cursor=newer.isoformat(),
        last_success_at=newer,
    )
    repository = OrderSyncRepository(
        FakeDatabase(FakeSession(run, cursor)),
        TokenCipher("test-only-order-pii-encryption-key-32-chars"),
    )

    result = asyncio.run(repository.complete_run(tenant_id, run_id, committed_at=older))

    assert result.status == "succeeded"
    assert cursor.committed_cursor == newer.isoformat()
    assert cursor.last_success_at == newer
