from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy.dialects import postgresql

from erp_api.models.sample_sync_run import SampleSyncRun
from erp_api.services.sample_sync_audit_repository import SampleSyncAuditRepository


class FakeSession:
    def __init__(self, *, rowcount: int = 1) -> None:
        self.added: list[object] = []
        self.statements: list[object] = []
        self.commits = 0
        self.rowcount = rowcount

    def add(self, value: object) -> None:
        self.added.append(value)

    async def execute(self, statement):
        self.statements.append(statement)
        return SimpleNamespace(rowcount=self.rowcount)

    async def commit(self) -> None:
        self.commits += 1


class FakeDatabase:
    def __init__(self, session: FakeSession) -> None:
        self.session = session

    @asynccontextmanager
    async def system_session_factory(self):
        yield self.session


@pytest.mark.asyncio
async def test_start_feishu_creates_scoped_postgres_to_feishu_run() -> None:
    session = FakeSession()
    repository = SampleSyncAuditRepository(FakeDatabase(session))  # type: ignore[arg-type]
    tenant_id = UUID(int=10_000)
    shop_id = UUID(int=20_000)

    run_id = await repository.start_feishu(
        tenant_id=tenant_id,
        shop_id=shop_id,
        started_at=datetime(2026, 9, 10, tzinfo=UTC),
    )

    assert isinstance(run_id, UUID)
    assert len(session.added) == 1
    run = session.added[0]
    assert isinstance(run, SampleSyncRun)
    assert run.tenant_id == tenant_id
    assert run.shop_id == shop_id
    assert run.sync_type == "postgres_to_feishu"
    assert run.source_type == "postgresql"
    assert run.status == "running"
    assert session.commits == 1


@pytest.mark.asyncio
async def test_finish_feishu_persists_request_ids_failure_code_and_counts() -> None:
    session = FakeSession()
    repository = SampleSyncAuditRepository(FakeDatabase(session))  # type: ignore[arg-type]
    tenant_id = UUID(int=10_000)
    shop_id = UUID(int=20_000)
    run_id = UUID(int=30_000)

    await repository.finish_feishu(
        tenant_id=tenant_id,
        shop_id=shop_id,
        run_id=run_id,
        status="failed",
        records_read=12,
        feishu_created=5,
        feishu_updated=4,
        request_ids=["log-1", "log-2"],
        error_code="99991400",
        finished_at=datetime(2026, 9, 10, tzinfo=UTC),
    )

    statement = session.statements[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    params = compiled.params
    assert tenant_id in params.values()
    assert shop_id in params.values()
    assert run_id in params.values()
    assert params["status"] == "failed"
    assert params["records_read"] == 12
    assert params["feishu_created"] == 5
    assert params["feishu_updated"] == 4
    assert params["platform_request_ids"] == ["log-1", "log-2"]
    assert params["error_code"] == "99991400"
    assert "rate limited" not in repr(params)
    assert session.commits == 1


@pytest.mark.asyncio
async def test_finish_feishu_rejects_cross_shop_or_missing_run() -> None:
    session = FakeSession(rowcount=0)
    repository = SampleSyncAuditRepository(FakeDatabase(session))  # type: ignore[arg-type]

    with pytest.raises(LookupError, match="not found for this shop"):
        await repository.finish_feishu(
            tenant_id=UUID(int=10_000),
            shop_id=UUID(int=20_000),
            run_id=UUID(int=30_000),
            status="succeeded",
            records_read=0,
            feishu_created=0,
            feishu_updated=0,
            request_ids=[],
            error_code=None,
            finished_at=datetime(2026, 9, 10, tzinfo=UTC),
        )

    assert session.commits == 0
