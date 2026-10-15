from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from erp_api.services.sample_application_repository import (
    SampleApplicationRepository,
)


class FakeSession:
    def __init__(self, scalar_results: list[object]) -> None:
        self.scalar_results = scalar_results
        self.scalar_statements: list[object] = []
        self.executed_statements: list[object] = []
        self.commits = 0
        self.rollbacks = 0

    async def scalar(self, statement):
        self.scalar_statements.append(statement)
        return self.scalar_results.pop(0)

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1

    async def execute(self, statement):
        self.executed_statements.append(statement)


class FakeDatabase:
    def __init__(self, session: FakeSession) -> None:
        self.session = session
        self.sessions_opened = 0

    @asynccontextmanager
    async def system_session_factory(self):
        self.sessions_opened += 1
        yield self.session


def _workflow(**overrides):
    values = {
        "tenant_id": uuid4(),
        "shop_id": uuid4(),
        "sample_application_id": uuid4(),
        "assigned_bd_name": "BD A",
        "processing_status": "跟进中",
        "processing_result": "Pending",
        "business_note": "Old note",
        "assignment_version": 2,
        "assigned_at": None,
        "feishu_updated_at": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _apply(repository: SampleApplicationRepository, **overrides):
    values = {
        "record_id": "rec-1",
        "fields": {"分配BD": "BD B"},
        "event_id": "event-1",
        "event_source": "feishu_callback",
        "actor_id": "ou-user",
        "actor_name": "Test User",
        "assignment_recipient_open_id": "ou-bd-b",
        "occurred_at": datetime(2026, 9, 10, tzinfo=UTC),
    }
    values.update(overrides)
    return asyncio.run(repository.apply_feishu_business_fields(**values))


def test_feishu_event_claim_is_atomic_and_partial_fields_do_not_clear_others() -> None:
    workflow = _workflow()
    session = FakeSession([workflow, uuid4()])
    repository = SampleApplicationRepository(FakeDatabase(session))  # type: ignore[arg-type]

    result = _apply(repository)

    assert result == "applied"
    assert workflow.assigned_bd_name == "BD B"
    assert workflow.processing_status == "跟进中"
    assert workflow.processing_result == "Pending"
    assert workflow.business_note == "Old note"
    assert workflow.assignment_version == 3
    assert workflow.assigned_at == datetime(2026, 9, 10, tzinfo=UTC)
    assert session.commits == 1
    statement = session.scalar_statements[1]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    parameters = statement.compile(dialect=postgresql.dialect()).params
    assert (
        "ON CONFLICT ON CONSTRAINT "
        "uq_sample_application_events_tenant_shop_source_external DO NOTHING" in sql
    )
    assert "RETURNING sample_application_events.id" in sql
    assert parameters["tenant_id"] == workflow.tenant_id
    assert parameters["shop_id"] == workflow.shop_id
    assert parameters["sample_application_id"] == workflow.sample_application_id
    assert parameters["event_type"] == "business_fields_changed"
    assert parameters["event_source"] == "feishu_callback"
    assert parameters["external_event_id"] == "event-1"
    assert parameters["actor_id"] == "ou-user"
    assert parameters["actor_name"] == "Test User"
    assert parameters["before_data"]["assigned_bd_name"] == "BD A"
    assert parameters["after_data"]["assigned_bd_name"] == "BD B"
    assert len(session.executed_statements) == 2
    cancel_sql = str(
        session.executed_statements[0].compile(dialect=postgresql.dialect())
    )
    outbox_statement = session.executed_statements[1]
    outbox_sql = str(outbox_statement.compile(dialect=postgresql.dialect()))
    outbox_parameters = outbox_statement.compile(dialect=postgresql.dialect()).params
    assert "UPDATE sample_notification_outbox" in cancel_sql
    assert "INSERT INTO sample_notification_outbox" in outbox_sql
    assert "uq_sample_notification_outbox_assignment_recipient" in outbox_sql
    assert outbox_parameters["assignment_version"] == 3
    assert outbox_parameters["recipient_open_id"] == "ou-bd-b"
    assert outbox_parameters["payload"]["feishu_record_id"] == "rec-1"


def test_duplicate_feishu_event_does_not_mutate_workflow() -> None:
    workflow = _workflow()
    session = FakeSession([workflow, None])
    repository = SampleApplicationRepository(FakeDatabase(session))  # type: ignore[arg-type]

    result = _apply(repository)

    assert result == "duplicate"
    assert workflow.assigned_bd_name == "BD A"
    assert workflow.assignment_version == 2
    assert session.commits == 0
    assert session.rollbacks == 1
    assert session.executed_statements == []


def test_unchanged_feishu_event_is_still_claimed_for_idempotency() -> None:
    workflow = _workflow()
    session = FakeSession([workflow, uuid4()])
    repository = SampleApplicationRepository(FakeDatabase(session))  # type: ignore[arg-type]

    result = _apply(repository, fields={"备注": "Old note"})

    assert result == "unchanged"
    assert session.commits == 1
    assert session.rollbacks == 0


def test_stale_reverse_poll_does_not_overwrite_newer_callback_state() -> None:
    workflow = _workflow(feishu_updated_at=datetime(2026, 9, 10, 0, 5, tzinfo=UTC))
    session = FakeSession([workflow, uuid4()])
    repository = SampleApplicationRepository(FakeDatabase(session))  # type: ignore[arg-type]

    result = _apply(
        repository,
        event_source="feishu_poll",
        occurred_at=datetime(2026, 9, 10, tzinfo=UTC),
    )

    assert result == "unchanged"
    assert workflow.assigned_bd_name == "BD A"
    assert workflow.assignment_version == 2
    assert session.executed_statements == []


def test_clearing_assignment_cancels_old_task_without_creating_new_one() -> None:
    workflow = _workflow()
    session = FakeSession([workflow, uuid4()])
    repository = SampleApplicationRepository(FakeDatabase(session))  # type: ignore[arg-type]

    result = _apply(
        repository,
        fields={"分配BD": None},
        assignment_recipient_open_id=None,
    )

    assert result == "applied"
    assert workflow.assigned_bd_name is None
    assert workflow.assignment_version == 3
    assert len(session.executed_statements) == 1
    sql = str(session.executed_statements[0].compile(dialect=postgresql.dialect()))
    assert "UPDATE sample_notification_outbox" in sql


def test_repository_rejects_non_business_fields_before_opening_session() -> None:
    session = FakeSession([])
    database = FakeDatabase(session)
    repository = SampleApplicationRepository(database)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="business fields"):
        _apply(repository, fields={"TK申请状态": "SHIPPED"})

    assert database.sessions_opened == 0


def test_repository_rejects_empty_or_invalid_event_identity() -> None:
    session = FakeSession([])
    database = FakeDatabase(session)
    repository = SampleApplicationRepository(database)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="business fields"):
        _apply(repository, fields={})
    with pytest.raises(ValueError, match="event identity"):
        _apply(repository, event_id="")
    with pytest.raises(ValueError, match="event identity"):
        _apply(repository, event_id="x" * 256)

    assert database.sessions_opened == 0


def test_repository_rejects_assignment_without_recipient_identity() -> None:
    session = FakeSession([])
    database = FakeDatabase(session)
    repository = SampleApplicationRepository(database)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="recipient"):
        _apply(repository, assignment_recipient_open_id=None)

    assert database.sessions_opened == 0
