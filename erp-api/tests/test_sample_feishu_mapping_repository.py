from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy.dialects import postgresql

from erp_api.services.sample_feishu_mapping_repository import (
    SampleFeishuMappingRepository,
)


class FakeScalarResult:
    def __init__(self, rows: list[SimpleNamespace]) -> None:
        self._rows = rows

    def all(self) -> list[SimpleNamespace]:
        return self._rows


class FakeRowResult:
    def __init__(self, rows) -> None:
        self._rows = rows

    def all(self):
        return self._rows


class FakeSession:
    def __init__(self, rows: list[SimpleNamespace], execute_rows=None) -> None:
        self.rows = rows
        self.execute_rows = execute_rows or []
        self.statement = None
        self.commits = 0

    async def scalars(self, statement):
        self.statement = statement
        return FakeScalarResult(self.rows)

    async def execute(self, statement):
        self.statement = statement
        return FakeRowResult(self.execute_rows)

    async def commit(self) -> None:
        self.commits += 1


class FakeDatabase:
    def __init__(self, session: FakeSession) -> None:
        self.session = session

    @asynccontextmanager
    async def system_session_factory(self):
        yield self.session


def _workflow(
    application_id: UUID,
    record_id: str | None = None,
    feishu_updated_at=None,
) -> SimpleNamespace:
    return SimpleNamespace(
        sample_application_id=application_id,
        feishu_record_id=record_id,
        feishu_updated_at=feishu_updated_at,
        last_sync_at=None,
        sync_hash=None,
        sync_status="pending",
    )


@pytest.mark.asyncio
async def test_attach_records_is_tenant_shop_scoped_and_atomic() -> None:
    tenant_id = UUID(int=10_000)
    shop_id = UUID(int=20_000)
    first_id = UUID(int=1)
    second_id = UUID(int=2)
    rows = [_workflow(first_id), _workflow(second_id, "rec-2")]
    session = FakeSession(rows)
    repository = SampleFeishuMappingRepository(FakeDatabase(session))  # type: ignore[arg-type]

    attached = await repository.attach_records(
        tenant_id=tenant_id,
        shop_id=shop_id,
        mappings=[(first_id, "rec-1"), (second_id, "rec-2")],
    )

    compiled = session.statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "tenant_id" in sql
    assert "shop_id" in sql
    assert "FOR UPDATE" in sql
    assert tenant_id in compiled.params.values()
    assert shop_id in compiled.params.values()
    assert [row.feishu_record_id for row in rows] == ["rec-1", "rec-2"]
    assert attached == 2
    assert session.commits == 1


@pytest.mark.asyncio
async def test_attach_records_rejects_incomplete_shop_mapping_without_commit() -> None:
    tenant_id = UUID(int=10_000)
    shop_id = UUID(int=20_000)
    first_id = UUID(int=1)
    second_id = UUID(int=2)
    session = FakeSession([_workflow(first_id)])
    repository = SampleFeishuMappingRepository(FakeDatabase(session))  # type: ignore[arg-type]

    with pytest.raises(LookupError, match="incomplete for this shop"):
        await repository.attach_records(
            tenant_id=tenant_id,
            shop_id=shop_id,
            mappings=[(first_id, "rec-1"), (second_id, "rec-2")],
        )

    assert session.commits == 0
    assert session.rows[0].feishu_record_id is None


@pytest.mark.asyncio
async def test_attach_records_rejects_conflicting_existing_mapping() -> None:
    application_id = UUID(int=1)
    session = FakeSession([_workflow(application_id, "rec-old")])
    repository = SampleFeishuMappingRepository(FakeDatabase(session))  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="different Feishu record"):
        await repository.attach_records(
            tenant_id=UUID(int=10_000),
            shop_id=UUID(int=20_000),
            mappings=[(application_id, "rec-new")],
        )

    assert session.commits == 0
    assert session.rows[0].feishu_record_id == "rec-old"


@pytest.mark.asyncio
async def test_attach_records_rejects_duplicate_ids_before_database_access() -> None:
    session = FakeSession([])
    repository = SampleFeishuMappingRepository(FakeDatabase(session))  # type: ignore[arg-type]
    application_id = UUID(int=1)

    with pytest.raises(ValueError, match="mapping is duplicated"):
        await repository.attach_records(
            tenant_id=UUID(int=10_000),
            shop_id=UUID(int=20_000),
            mappings=[(application_id, "rec-1"), (application_id, "rec-2")],
        )

    assert session.statement is None
    assert session.commits == 0


@pytest.mark.asyncio
async def test_detach_records_clears_only_selected_shop_mappings() -> None:
    projected_at = object()
    rows = [
        _workflow(UUID(int=1), "rec-1", projected_at),
        _workflow(UUID(int=2), "rec-2", projected_at),
    ]
    session = FakeSession(rows)
    repository = SampleFeishuMappingRepository(FakeDatabase(session))  # type: ignore[arg-type]

    detached = await repository.detach_records(
        tenant_id=UUID(int=10_000),
        shop_id=UUID(int=20_000),
        record_ids=["rec-1", "rec-2"],
    )

    compiled = session.statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "tenant_id" in sql
    assert "shop_id" in sql
    assert "feishu_record_id IN" in sql
    assert "FOR UPDATE" in sql
    assert [row.feishu_record_id for row in rows] == [None, None]
    assert [row.feishu_updated_at for row in rows] == [None, None]
    assert [row.sync_status for row in rows] == ["pending", "pending"]
    assert detached == 2
    assert session.commits == 1


@pytest.mark.asyncio
async def test_mark_synced_persists_hash_and_time_for_matching_record() -> None:
    application_id = UUID(int=1)
    row = _workflow(application_id, "rec-1")
    session = FakeSession([row])
    repository = SampleFeishuMappingRepository(FakeDatabase(session))  # type: ignore[arg-type]
    synced_at = datetime(2026, 10, 4, tzinfo=UTC)

    await repository.mark_synced(
        tenant_id=UUID(int=10_000),
        shop_id=UUID(int=20_000),
        records=[(application_id, "rec-1", "a" * 64)],
        synced_at=synced_at,
    )

    assert row.last_sync_at == synced_at
    assert row.sync_hash == "a" * 64
    assert row.sync_status == "succeeded"
    assert session.commits == 1


@pytest.mark.asyncio
async def test_mark_synced_rejects_changed_mapping() -> None:
    application_id = UUID(int=1)
    session = FakeSession([_workflow(application_id, "rec-other")])
    repository = SampleFeishuMappingRepository(FakeDatabase(session))  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="mapping changed"):
        await repository.mark_synced(
            tenant_id=UUID(int=10_000),
            shop_id=UUID(int=20_000),
            records=[(application_id, "rec-1", "a" * 64)],
            synced_at=datetime.now(UTC),
        )

    assert session.commits == 0


@pytest.mark.asyncio
async def test_mark_failed_preserves_last_successful_hash() -> None:
    application_id = UUID(int=1)
    row = _workflow(application_id, "rec-1")
    row.sync_hash = "a" * 64
    session = FakeSession([row])
    repository = SampleFeishuMappingRepository(FakeDatabase(session))  # type: ignore[arg-type]

    await repository.mark_failed(
        tenant_id=UUID(int=10_000),
        shop_id=UUID(int=20_000),
        application_ids=[application_id],
    )

    assert row.sync_status == "failed"
    assert row.sync_hash == "a" * 64
    assert session.commits == 1


@pytest.mark.asyncio
async def test_poll_states_return_only_mapped_record_ids() -> None:
    modified_at = object()
    session = FakeSession(
        [],
        [("rec-1", modified_at, "BD A", "跟进中", "通过", "Note")],
    )
    repository = SampleFeishuMappingRepository(FakeDatabase(session))  # type: ignore[arg-type]

    result = await repository.list_poll_states(["rec-1", "rec-unmapped"])

    compiled = session.statement.compile(dialect=postgresql.dialect())
    assert "feishu_record_id" in str(compiled)
    assert result["rec-1"].updated_at is modified_at
    assert result["rec-1"].business_fields == {
        "分配BD": "BD A",
        "处理状态": "跟进中",
        "处理结果": "通过",
        "备注": "Note",
    }


@pytest.mark.asyncio
async def test_poll_states_reject_duplicate_record_ids() -> None:
    session = FakeSession([])
    repository = SampleFeishuMappingRepository(FakeDatabase(session))  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="identities"):
        await repository.list_poll_states(["rec-1", "rec-1"])

    assert session.statement is None
