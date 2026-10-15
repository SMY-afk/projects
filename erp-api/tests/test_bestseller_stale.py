from __future__ import annotations

import asyncio
from datetime import date
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from erp_api.models.bestseller_snapshot import BestsellerSnapshot
from erp_api.services.bestseller_repository import (
    BestsellerRepository,
    BestsellerSnapshotQuery,
)


class FakeDatabase:
    def __init__(self, session) -> None:
        self._session = session

    async def session(self, tenant_id):
        yield self._session


class FakeSession:
    def __init__(self, rowcount: int = 1) -> None:
        self.rowcount = rowcount
        self.statements = []
        self.commits = 0

    async def execute(self, statement):
        self.statements.append(statement)
        return SimpleNamespace(rowcount=self.rowcount)

    async def commit(self):
        self.commits += 1


def _query(shop_id):
    return BestsellerSnapshotQuery(
        shop_id=shop_id,
        entity_type="creator",
        reference_date=date(2026, 8, 19),
        time_slot="30D",
        currency="LOCAL",
        author_type="AFFILIATE",
    )


def test_snapshot_exposes_stale_status_without_changing_entries() -> None:
    assert BestsellerSnapshot.__table__.c.is_stale.nullable is False
    assert BestsellerSnapshot.__table__.c.last_error_category.nullable is True
    assert BestsellerSnapshot.__table__.c.last_error_at.nullable is True


def test_mark_snapshot_stale_matches_full_query_and_never_deletes_entries() -> None:
    tenant_id, shop_id = uuid4(), uuid4()
    session = FakeSession()
    repository = BestsellerRepository(FakeDatabase(session))

    marked = asyncio.run(
        repository.mark_snapshot_stale(
            tenant_id,
            _query(shop_id),
            "reauthorization_required",
        )
    )

    assert marked is True
    assert session.commits == 1
    assert len(session.statements) == 1
    compiled = session.statements[0].compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "UPDATE bestseller_snapshots" in sql
    assert "bestseller_entries" not in sql
    assert "tenant_id" in sql
    assert "shop_id" in sql
    assert "entity_type" in sql
    assert "reference_date" in sql
    assert "time_slot" in sql
    assert "currency" in sql
    assert "author_type" in sql
    assert "AFFILIATE" in compiled.params.values()
    assert "reauthorization_required" in compiled.params.values()


def test_mark_stale_reports_no_previous_success_without_creating_snapshot() -> None:
    session = FakeSession(rowcount=0)
    repository = BestsellerRepository(FakeDatabase(session))

    marked = asyncio.run(
        repository.mark_snapshot_stale(
            uuid4(),
            _query(uuid4()),
            "rate_limited",
        )
    )

    assert marked is False
    assert len(session.statements) == 1
    assert session.commits == 1
