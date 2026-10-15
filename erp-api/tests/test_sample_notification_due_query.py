from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from erp_api.services.sample_notification_repository import (
    SampleNotificationRepository,
)


class FakeResult:
    def __init__(self, rows) -> None:
        self._rows = rows

    def all(self):
        return self._rows


class FakeSession:
    def __init__(self, rows) -> None:
        self.rows = rows
        self.statement = None

    async def execute(self, statement):
        self.statement = statement
        return FakeResult(self.rows)


class FakeDatabase:
    def __init__(self, session) -> None:
        self.session = session

    @asynccontextmanager
    async def system_session_factory(self):
        yield self.session


@pytest.mark.asyncio
async def test_due_query_includes_pending_retry_and_stale_processing() -> None:
    tenant_id, event_id = uuid4(), uuid4()
    session = FakeSession([(tenant_id, event_id, 2)])
    repository = SampleNotificationRepository(FakeDatabase(session))

    rows = await repository.list_due(
        now=datetime(2026, 9, 10, tzinfo=UTC),
        processing_timeout=timedelta(minutes=10),
    )

    sql = str(session.statement.compile(dialect=postgresql.dialect()))
    assert "sample_notification_outbox.status" in sql
    assert "sample_notification_outbox.next_attempt_at" in sql
    assert "sample_notification_outbox.updated_at" in sql
    assert rows == [(tenant_id, event_id, 2)]


@pytest.mark.asyncio
async def test_due_query_can_be_scoped_to_one_tenant_and_shop() -> None:
    tenant_id, shop_id, event_id = uuid4(), uuid4(), uuid4()
    session = FakeSession([(tenant_id, event_id, 0)])
    repository = SampleNotificationRepository(FakeDatabase(session))

    rows = await repository.list_due(
        now=datetime(2026, 9, 10, tzinfo=UTC),
        processing_timeout=timedelta(minutes=10),
        tenant_id=tenant_id,
        shop_id=shop_id,
    )

    sql = str(session.statement.compile(dialect=postgresql.dialect()))
    assert "sample_notification_outbox.tenant_id" in sql
    assert "sample_notification_outbox.shop_id" in sql
    assert rows == [(tenant_id, event_id, 0)]
