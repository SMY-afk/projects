from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from erp_api.services.bestseller_read_repository import BestsellerReadRepository
from erp_api.services.bestseller_repository import BestsellerSnapshotQuery


class FakeResult:
    def __init__(self, rows) -> None:
        self.rows = rows

    def one_or_none(self):
        return self.rows[0] if self.rows else None

    def all(self):
        return self.rows


class FakeSession:
    def __init__(self, snapshot, entries) -> None:
        self.responses = [FakeResult([snapshot]), FakeResult(entries)]
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return self.responses.pop(0)


class FakeDatabase:
    def __init__(self, session) -> None:
        self.session_value = session

    async def session(self, tenant_id):
        yield self.session_value


def test_read_snapshot_filters_full_query_and_selects_no_raw_payload() -> None:
    tenant_id, shop_id, snapshot_id = uuid4(), uuid4(), uuid4()
    refreshed_at = datetime(2026, 8, 20, 4, tzinfo=UTC)
    snapshot = SimpleNamespace(
        id=snapshot_id,
        platform_request_id="request-1",
        entry_count=1,
        is_stale=False,
        last_error_category=None,
        last_error_at=None,
        refreshed_at=refreshed_at,
    )
    entries = [
        SimpleNamespace(
            external_id="creator-1",
            rank=1,
            display_name="Creator 1",
            gmv_range_raw="$1K-$2K",
            gmv_currency_context="LOCAL",
            extensions={"followers": 10},
        )
    ]
    session = FakeSession(snapshot, entries)
    repository = BestsellerReadRepository(FakeDatabase(session))
    query = BestsellerSnapshotQuery(
        shop_id=shop_id,
        entity_type="creator",
        reference_date=date(2026, 8, 19),
        time_slot="30D",
        currency="LOCAL",
        author_type="AFFILIATE",
    )

    result = asyncio.run(repository.get_snapshot(tenant_id, query))

    assert result is not None
    assert result.refreshed_at == refreshed_at
    assert result.entries[0].extensions == {"followers": 10}
    snapshot_sql = str(session.statements[0].compile(dialect=postgresql.dialect()))
    entry_sql = str(session.statements[1].compile(dialect=postgresql.dialect()))
    for dimension in (
        "tenant_id",
        "shop_id",
        "entity_type",
        "reference_date",
        "time_slot",
        "currency",
        "author_type",
    ):
        assert dimension in snapshot_sql
    assert "tenant_id" in entry_sql
    assert "shop_id" in entry_sql
    assert "snapshot_id" in entry_sql
    assert "raw_payload" not in entry_sql
