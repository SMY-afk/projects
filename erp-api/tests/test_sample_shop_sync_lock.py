from contextlib import asynccontextmanager
from uuid import uuid4

import pytest

from erp_api.services.sample_shop_sync_lock import (
    SampleShopSyncLock,
    sample_shop_lock_key,
)


class FakeConnection:
    def __init__(self, acquired: bool) -> None:
        self.acquired = acquired
        self.statements = []

    async def scalar(self, statement):
        self.statements.append(statement)
        return self.acquired


class FakeEngine:
    def __init__(self, connection) -> None:
        self.connection = connection
        self.transaction_exited = False

    @asynccontextmanager
    async def begin(self):
        try:
            yield self.connection
        finally:
            self.transaction_exited = True


@pytest.mark.asyncio
async def test_lock_is_scoped_by_tenant_and_shop_and_released_with_transaction() -> None:
    tenant_id, shop_id, other_shop_id = uuid4(), uuid4(), uuid4()
    assert sample_shop_lock_key(tenant_id, shop_id) == sample_shop_lock_key(
        tenant_id, shop_id
    )
    assert sample_shop_lock_key(tenant_id, shop_id) != sample_shop_lock_key(
        tenant_id, other_shop_id
    )
    connection = FakeConnection(True)
    engine = FakeEngine(connection)
    lock = SampleShopSyncLock(type("Database", (), {"engine": engine})())

    async with lock.acquire(tenant_id, shop_id) as acquired:
        assert acquired is True
        assert engine.transaction_exited is False

    assert engine.transaction_exited is True
    assert len(connection.statements) == 1


@pytest.mark.asyncio
async def test_lock_reports_contention_without_entering_sync() -> None:
    connection = FakeConnection(False)
    engine = FakeEngine(connection)
    lock = SampleShopSyncLock(type("Database", (), {"engine": engine})())

    async with lock.acquire(uuid4(), uuid4()) as acquired:
        assert acquired is False

    assert engine.transaction_exited is True
