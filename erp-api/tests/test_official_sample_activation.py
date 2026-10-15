from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import Column, DateTime, MetaData, String, Table, create_engine, select
from sqlalchemy.dialects import postgresql

from erp_api.services.sample_feishu_source_repository import (
    build_committed_sample_query,
)
from erp_api.services.sample_post_source_work_gate import SamplePostSourceWorkGate
from erp_api.services.sample_type_policy import sample_activation_condition


def _assert_official_discovery_time(statement):
    sql = str(
        statement.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert (
        "sample_applications.source_type = 'official_api' AND "
        "sample_applications.first_seen_at >="
    ) in sql
    assert "sample_applications.tiktok_applied_at >=" in sql
    assert "sample_ingest_batches.status = 'complete'" in sql
    assert "sample_applications.is_current_projection IS true" in sql


def test_feishu_entry_accepts_official_discovery_without_application_time():
    _assert_official_discovery_time(
        build_committed_sample_query(
            tenant_id=uuid4(),
            shop_id=uuid4(),
            after_application_id=None,
            limit=200,
            activation_at=datetime(2026, 9, 15, tzinfo=UTC),
            application_ids=frozenset({uuid4()}),
        )
    )


def test_new_official_sample_requires_a_recorded_cooperation_precheck():
    sql = str(
        build_committed_sample_query(
            tenant_id=uuid4(),
            shop_id=uuid4(),
            after_application_id=None,
            limit=200,
        ).compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )
    assert (
        "sample_application_events.event_source = 'feishu_cooperation_precheck'" in sql
    )
    assert "sample_cooperation_allowed" in sql
    assert (
        "sample_application_events.sample_application_id = sample_applications.id"
        in sql
    )
    assert "sample_application_workflows.feishu_record_id IS NOT NULL" in sql


@pytest.mark.asyncio
async def test_missing_sample_gate_uses_the_same_official_discovery_boundary():
    class Session:
        async def scalar(self, statement):
            _assert_official_discovery_time(statement)
            return uuid4()

    class Database:
        @asynccontextmanager
        async def system_session_factory(self):
            yield Session()

    gate = SamplePostSourceWorkGate(
        Database(), activation_at=datetime(2026, 9, 15, tzinfo=UTC)
    )
    assert await gate._has_missing_sample(uuid4(), uuid4(), frozenset({uuid4()}))


@pytest.mark.parametrize(
    "source,kind,applied,discovered,expected",
    [
        ("official_api", "free", None, "2026-10-12", True),
        ("official_api", "free", "2026-09-01", "2026-10-12", True),
        ("official_api", "free", "2026-10-12", "2026-09-01", False),
        ("hubstudio_cdp", "free", None, "2026-10-12", False),
        ("hubstudio_cdp", "free", "2026-10-12", "2026-09-01", True),
        ("hubstudio_cdp", "refundable", None, "2026-10-12", True),
        ("unknown", "free", "2026-10-12", "2026-10-12", False),
    ],
)
def test_activation_keeps_source_specific_boundaries(
    source, kind, applied, discovered, expected
):
    metadata = MetaData()
    table = Table(
        "samples",
        metadata,
        Column("source_type", String),
        Column("sample_type", String),
        Column("tiktok_applied_at", DateTime),
        Column("first_seen_at", DateTime),
    )
    model = SimpleNamespace(**{column.name: column for column in table.c})
    engine = create_engine("sqlite://")
    metadata.create_all(engine)
    try:
        with engine.begin() as connection:
            connection.execute(
                table.insert().values(
                    source_type=source,
                    sample_type=kind,
                    tiktok_applied_at=datetime.fromisoformat(applied)
                    if applied
                    else None,
                    first_seen_at=datetime.fromisoformat(discovered),
                )
            )
            result = connection.scalar(
                select(table.c.source_type).where(
                    sample_activation_condition(
                        datetime(2026, 9, 15, tzinfo=UTC), model
                    )
                )
            )
            assert (result is not None) is expected
    finally:
        engine.dispose()
