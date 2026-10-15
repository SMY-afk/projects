from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.dialects import postgresql

from scripts import local_sample_metadata_db as metadata
from tests.test_local_sample_metadata_rules import candidate


class Reply:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows

    def one_or_none(self):
        return self.rows[0] if self.rows else None


def database(rows):
    statements = []

    class Session:
        async def execute(self, statement):
            statements.append(statement)
            return Reply(rows)

        async def scalars(self, statement):
            statements.append(statement)
            return Reply(rows)

    @asynccontextmanager
    async def factory():
        yield Session()

    return SimpleNamespace(system_session_factory=factory), statements


@pytest.mark.asyncio
async def test_candidate_probe_is_read_only_scoped_and_rejects_malformed_marker(monkeypatch):
    now = datetime.now(UTC)
    app, workflow, batch = candidate(now)
    app.id, app.platform_application_id = "db-one", "one"
    db, statements = database([(app, workflow, batch)])
    monkeypatch.setattr(metadata, "require_source", AsyncMock(return_value={"source_batch_id": "batch"}))
    result = await metadata.candidates(db, now - timedelta(days=1), now=now)
    assert len(result["rows"]) == 1
    assert str(statements[0]) == "SET TRANSACTION READ ONLY"
    sql = str(statements[1].compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert metadata.LOCAL_SHOP in sql and metadata.LOCAL_TENANT in sql
    assert "is_proactive_invitation" in sql and "IS NULL" in sql
    assert "official_api" in sql and "PENDING" in sql and " LIMIT 500" in sql
    app.raw_payload = {"is_proactive_invitation": "false"}
    assert not (await metadata.candidates(db, now - timedelta(days=1), now=now))["rows"]


@pytest.mark.asyncio
async def test_latest_running_source_is_not_success_even_with_fresh_timestamps():
    now = datetime.now(UTC)
    run = SimpleNamespace(status="running", finished_at=now)
    batch = SimpleNamespace(status="complete", finished_at=now,
                            page_count=1, expected_total=1, captured_total=1)
    db, statements = database([(run, batch)])
    with pytest.raises(RuntimeError, match="not_complete_success"):
        await metadata.require_source(db, now=now)
    assert str(statements[0]) == "SET TRANSACTION READ ONLY"


@pytest.mark.asyncio
async def test_unequal_source_totals_never_pass():
    now = datetime.now(UTC)
    run = SimpleNamespace(status="succeeded", finished_at=now)
    batch = SimpleNamespace(status="complete", finished_at=now,
                            page_count=1, expected_total=2, captured_total=1)
    db, _ = database([(run, batch)])
    with pytest.raises(RuntimeError, match="not_complete_success"):
        await metadata.require_source(db, now=now)
