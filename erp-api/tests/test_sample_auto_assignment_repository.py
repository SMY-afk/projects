from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from erp_api.services.sample_auto_assignment_repository import (
    SampleAutoAssignmentRepository,
    _creator_assignment_key,
)
from erp_api.services.sample_auto_assignment_service import PendingSampleAssignment
from erp_api.services.sample_bd_assignment import (
    AssignmentDecision,
    BdWorkload,
    select_bd_for_level,
)


class Result:
    def __init__(self, rows) -> None:
        self._rows = rows

    def all(self):
        return self._rows


class Session:
    def __init__(
        self,
        *,
        application=None,
        workflow=None,
        rows=(),
        average_rows=(),
        historical_assignment_id=None,
        historical_sent_outbox_id=None,
    ) -> None:
        self.application = application or SimpleNamespace(
            raw_payload={}, platform_status="PENDING", is_current_projection=True,
            is_approvable=True, approve_expiration_at=datetime(2099, 1, 1, tzinfo=UTC),
        )
        self.workflow = workflow
        self.rows = rows
        self.average_rows = average_rows
        self.historical_assignment_id = historical_assignment_id
        self.historical_sent_outbox_id = historical_sent_outbox_id
        self.statements = []
        self.commits = 0
        self.rollbacks = 0

    async def scalar(self, statement):
        self.statements.append(statement)
        sql = str(statement.compile(dialect=postgresql.dialect()))
        if "FROM sample_application_events" in sql:
            return self.historical_assignment_id
        if "FROM sample_notification_outbox" in sql:
            return self.historical_sent_outbox_id
        if "FROM sample_applications" in sql:
            return self.application
        return self.workflow

    async def execute(self, statement):
        self.statements.append(statement)
        sql = str(statement.compile(dialect=postgresql.dialect()))
        if "avg(sample_applications.creator_gmv_minor)" in sql:
            return Result(self.average_rows)
        return Result(self.rows if sql.startswith("SELECT") else ())

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


class Database:
    def __init__(self, session) -> None:
        self.session = session

    @asynccontextmanager
    async def system_session_factory(self):
        yield self.session


def _request():
    return PendingSampleAssignment(
        tenant_id=uuid4(),
        shop_id=uuid4(),
        application_id=uuid4(),
        creator_level="L3",
        category="测试",
        assignment_key="username:creator-one",
    )


def test_creator_assignment_key_prefers_username_across_shops() -> None:
    application = SimpleNamespace(
        creator_username=" @Creator-One ",
        creator_open_id="shop-specific-open-id",
        platform_application_id="application-1",
    )

    assert _creator_assignment_key(application) == "username:creator-one"


@pytest.mark.asyncio
async def test_list_pending_uses_latest_classified_source_and_is_bounded() -> None:
    request = _request()
    application = SimpleNamespace(
        id=request.application_id,
        creator_level="L3",
        platform_application_id="creator-group:sample-1",
        creator_open_id=None,
        creator_username="Creator-One",
        creator_gmv_minor=2_500_000,
        creator_gmv_currency="USD",
        sample_type="free",
    )
    session = Session(
        rows=[(application, SimpleNamespace())],
        average_rows=[("L3", "free", Decimal("2_000_000.4")),
                      ("L3", "refundable", Decimal("4_000_000"))],
    )
    repository = SampleAutoAssignmentRepository(
        Database(session),
        category="测试",
        batch_limit=1,
        activation_at=datetime(2026, 9, 14, tzinfo=UTC),
    )

    pending = await repository.list_pending(
        request.tenant_id,
        request.shop_id,
        application_ids=frozenset({request.application_id}),
    )

    assert pending == (
        replace(
            request,
            creator_gmv_minor=2_500_000,
            estimated_level_gmv_minor=2_000_000,
        ),
    )
    compiled = session.statements[0].compile(dialect=postgresql.dialect())
    sql = str(compiled)
    params = compiled.params
    assert "sample_applications.platform_status" in sql
    assert "sample_application_workflows.feishu_record_id IS NOT NULL" in sql
    assert "sample_applications.tiktok_applied_at >=" not in sql
    assert "sample_applications.first_seen_at >=" not in sql
    assert "sample_applications.source_type" in sql
    assert "row_number() OVER" in sql
    assert "sample_applications.is_current_projection IS true" in sql
    assert "sample_applications.is_approvable IS true" in sql
    assert "sample_applications.approve_expiration_at >" in sql
    assert ("ziniao_group_projection", "parent_application_id") in params.values()
    assert "manual_assignment_deleted" in params.values()
    assert "IS NOT true" in sql
    assert "sample_applications.id IN" in sql
    assert "sample_application_events.event_type" in sql
    assert "sample_cooperation_allowed" in params.values()
    assert "feishu_cooperation_precheck" in params.values()
    assert "sample_notification_outbox.status" in sql
    assert "sent" in params.values()
    assert "NOT (EXISTS" in sql
    assert "is_proactive_invitation" in params.values()
    assert "IS NOT NULL" in sql
    assert "IS false" not in sql
    assert "LIMIT" in sql
    average_sql = str(
        session.statements[1].compile(dialect=postgresql.dialect())
    )
    assert "avg(sample_applications.creator_gmv_minor)" in average_sql
    assert "sample_applications.first_seen_at >=" in average_sql
    assert "sample_applications.creator_gmv_currency" in average_sql


@pytest.mark.asyncio
async def test_list_pending_keeps_activation_gate_without_source_scope() -> None:
    session = Session(rows=[])
    repository = SampleAutoAssignmentRepository(
        Database(session),
        category="测试",
        batch_limit=1,
        activation_at=datetime(2026, 9, 14, tzinfo=UTC),
    )

    await repository.list_pending(uuid4(), uuid4())

    sql = str(session.statements[0].compile(dialect=postgresql.dialect()))
    assert "sample_applications.tiktok_applied_at >=" in sql
    assert "sample_applications.first_seen_at >=" in sql


@pytest.mark.asyncio
async def test_list_pending_can_exclude_previously_blocked_for_quiet_gate() -> None:
    request = _request()
    session = Session(rows=[])
    repository = SampleAutoAssignmentRepository(
        Database(session),
        category="测试",
        batch_limit=1,
        activation_at=datetime(2026, 9, 14, tzinfo=UTC),
    )

    await repository.list_pending(
        request.tenant_id,
        request.shop_id,
        application_ids=frozenset({request.application_id}),
        exclude_previously_blocked=True,
    )

    compiled = session.statements[0].compile(dialect=postgresql.dialect())
    assert "bd_auto_blocked" in compiled.params.values()
    assert "NOT (EXISTS" in str(compiled)


@pytest.mark.asyncio
async def test_transaction_persists_assignment_audit_and_outbox_atomically() -> None:
    request = _request()
    workflow = SimpleNamespace(
        tenant_id=request.tenant_id,
        shop_id=request.shop_id,
        sample_application_id=request.application_id,
        assigned_bd_name=None,
        assignment_version=0,
        assigned_at=None,
        processing_status=None,
        feishu_record_id="rec-sample-1",
    )
    session = Session(workflow=workflow)
    repository = SampleAutoAssignmentRepository(
        Database(session),
        category="测试",
        batch_limit=1,
        activation_at=datetime(2026, 9, 14, tzinfo=UTC),
    )
    decision = AssignmentDecision(
        assigned_bd_name="李鸿程",
        creator_level="L3",
        assigned_bd_id="rec-bd-1",
        recipient_open_id="ou-bd-1",
        decision_reason="selected",
    )

    async with repository.transaction(request) as transaction:
        assert await transaction.is_assigned() is False
        await transaction.record_decision(decision, rule_version="bd-v1")

    assert workflow.assigned_bd_name == "李鸿程"
    assert workflow.assignment_version == 1
    assert workflow.processing_status == "待处理"
    assert session.commits == 1
    sql = [
        str(item.compile(dialect=postgresql.dialect())) for item in session.statements
    ]
    assert any("pg_advisory_xact_lock" in item for item in sql)
    assert any("INSERT INTO sample_application_events" in item for item in sql)
    assert any("INSERT INTO sample_notification_outbox" in item for item in sql)


@pytest.mark.asyncio
async def test_historical_auto_assignment_blocks_reassignment_after_field_clear() -> (
    None
):
    request = _request()
    workflow = SimpleNamespace(assigned_bd_name=None)
    session = Session(workflow=workflow, historical_assignment_id=uuid4())
    repository = SampleAutoAssignmentRepository(
        Database(session),
        category="测试",
        batch_limit=1,
        activation_at=datetime(2026, 9, 14, tzinfo=UTC),
    )

    async with repository.transaction(request) as transaction:
        assert await transaction.is_assigned() is True

    sql = "\n".join(
        str(item.compile(dialect=postgresql.dialect()))
        for item in session.statements
    )
    assert "sample_application_events.event_type" in sql
    assert "sample_application_events.event_source" in sql


@pytest.mark.asyncio
async def test_sent_notification_blocks_reassignment_after_field_clear() -> None:
    request = _request()
    workflow = SimpleNamespace(assigned_bd_name=None)
    session = Session(
        workflow=workflow,
        historical_sent_outbox_id=uuid4(),
    )
    repository = SampleAutoAssignmentRepository(
        Database(session),
        category="测试",
        batch_limit=1,
        activation_at=datetime(2026, 9, 14, tzinfo=UTC),
    )

    async with repository.transaction(request) as transaction:
        assert await transaction.is_assigned() is True

    sql = "\n".join(
        str(item.compile(dialect=postgresql.dialect()))
        for item in session.statements
    )
    assert "sample_notification_outbox.status" in sql


@pytest.mark.asyncio
async def test_manual_deletion_blocks_stale_pending_request_in_transaction() -> None:
    request = _request()
    application = SimpleNamespace(
        raw_payload={"manual_assignment_deleted": True}
    )
    workflow = SimpleNamespace(assigned_bd_name=None)
    session = Session(application=application, workflow=workflow)
    repository = SampleAutoAssignmentRepository(
        Database(session),
        category="测试",
        batch_limit=1,
        activation_at=datetime(2026, 9, 14, tzinfo=UTC),
    )

    async with repository.transaction(request) as transaction:
        assert await transaction.is_assigned() is True

    sql = "\n".join(
        str(item.compile(dialect=postgresql.dialect()))
        for item in session.statements
    )
    assert "FROM sample_applications" in sql
    assert "FOR UPDATE" in sql


@pytest.mark.asyncio
async def test_expired_application_blocks_stale_request_in_transaction() -> None:
    request = _request()
    application = SimpleNamespace(
        raw_payload={}, platform_status="PENDING", is_current_projection=True,
        is_approvable=True, approve_expiration_at=datetime(2020, 1, 1, tzinfo=UTC),
    )
    session = Session(application=application, workflow=SimpleNamespace(assigned_bd_name=None))
    repository = SampleAutoAssignmentRepository(
        Database(session), category="测试", batch_limit=1,
        activation_at=datetime(2026, 9, 14, tzinfo=UTC),
    )

    async with repository.transaction(request) as transaction:
        assert await transaction.is_assigned() is True


@pytest.mark.asyncio
async def test_expired_group_member_blocks_assignment_in_transaction() -> None:
    request = _request()
    application = SimpleNamespace(
        raw_payload={"ziniao_group_projection": {"source_item_ids": ["parent", "child"]}},
        platform_status="PENDING", is_current_projection=True,
        is_approvable=True, approve_expiration_at=datetime(2099, 1, 1, tzinfo=UTC),
    )
    session = Session(
        application=application,
        workflow=SimpleNamespace(assigned_bd_name=None),
        rows=[
            ("parent", "PENDING", True, datetime(2099, 1, 1, tzinfo=UTC)),
            ("child", "OVERDUE_CANCELLED", True, datetime(2099, 1, 1, tzinfo=UTC)),
        ],
    )
    repository = SampleAutoAssignmentRepository(
        Database(session), category="测试", batch_limit=1,
        activation_at=datetime(2026, 9, 14, tzinfo=UTC),
    )

    async with repository.transaction(request) as transaction:
        assert await transaction.is_assigned() is True


@pytest.mark.asyncio
async def test_creator_affinity_is_cross_shop_and_limited_to_seven_days() -> None:
    request = _request()
    session = Session(workflow=SimpleNamespace(assigned_bd_name=None))
    repository = SampleAutoAssignmentRepository(
        Database(session),
        category="测试",
        batch_limit=1,
        activation_at=datetime(2026, 9, 14, tzinfo=UTC),
    )

    async with repository.transaction(request) as transaction:
        assert await transaction.load_creator_bd_name() is None

    compiled = [
        item.compile(dialect=postgresql.dialect()) for item in session.statements
    ]
    sql = "\n".join(str(item) for item in compiled)
    assert "sample_application_workflows.assigned_at >=" in sql
    assert "max(sample_application_events.occurred_at)" not in sql
    affinity_query = next(
        str(item) for item in compiled
        if "FROM sample_application_workflows JOIN sample_applications" in str(item)
    )
    assert "sample_application_workflows.shop_id =" not in affinity_query


@pytest.mark.asyncio
async def test_creator_affinity_recovers_sent_assignment_cleared_by_reverse_poll() -> None:
    class ClearedWorkflowSession(Session):
        async def scalar(self, statement):
            self.statements.append(statement)
            sql = str(statement.compile(dialect=postgresql.dialect()))
            if "FROM sample_application_events JOIN" in sql:
                return "原BD"
            if "FROM sample_applications" in sql:
                return self.application
            if "FROM sample_application_workflows" in sql and "FOR UPDATE" in sql:
                return self.workflow
            return None

    session = ClearedWorkflowSession(workflow=SimpleNamespace(assigned_bd_name=None))
    repository = SampleAutoAssignmentRepository(
        Database(session), category="测试", batch_limit=1,
        activation_at=datetime(2026, 9, 14, tzinfo=UTC),
    )

    async with repository.transaction(_request()) as transaction:
        assert await transaction.load_creator_bd_name() == "原BD"

    sql = "\n".join(str(item.compile(dialect=postgresql.dialect())) for item in session.statements)
    assert "sample_notification_outbox.status" in sql
    assert "sample_application_events.occurred_at >= " in sql


@pytest.mark.asyncio
async def test_creator_affinity_prefers_earliest_sent_owner_to_later_workflow() -> None:
    class MixedHistorySession(Session):
        async def scalar(self, statement):
            self.statements.append(statement)
            sql = str(statement.compile(dialect=postgresql.dialect()))
            if "FROM sample_application_events JOIN" in sql:
                return "原BD"
            if "FROM sample_applications" in sql:
                return self.application
            return SimpleNamespace(assigned_bd_name="后来的BD")

    session = MixedHistorySession(workflow=SimpleNamespace(assigned_bd_name=None))
    repository = SampleAutoAssignmentRepository(
        Database(session), category="测试", batch_limit=1,
        activation_at=datetime(2026, 9, 14, tzinfo=UTC),
    )
    async with repository.transaction(_request()) as transaction:
        assert await transaction.load_creator_bd_name() == "原BD"


@pytest.mark.asyncio
async def test_compensation_is_scoped_to_shop_level_and_unconsumed_event() -> None:
    request = _request()
    opened = SimpleNamespace(
        after_data={"bd_name": "example-44e1fbf547ff", "creator_level": "L3"},
        external_event_id="bd-compensation:application-id",
    )
    session = Session(
        workflow=SimpleNamespace(assigned_bd_name=None),
        historical_assignment_id=opened,
    )
    repository = SampleAutoAssignmentRepository(
        Database(session), category="测试", batch_limit=1,
        activation_at=datetime(2026, 9, 14, tzinfo=UTC),
    )

    async with repository.transaction(request) as transaction:
        assert await transaction.load_compensation_bd_name() == "example-44e1fbf547ff"

    statement = next(
        item for item in session.statements
        if "bd_assignment_compensation_opened" in str(item.compile(dialect=postgresql.dialect()).params)
    )
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "sample_application_events.shop_id =" in sql
    assert "sample_application_events.after_data" in sql
    assert "bd_assignment_compensation_consumed" in compiled.params.values()
    assert "SKIP LOCKED" in sql


@pytest.mark.asyncio
async def test_load_workloads_uses_assignment_record_enriched_roster() -> None:
    request = _request()
    workflow = SimpleNamespace(assigned_bd_name=None)
    session = Session(workflow=workflow)
    repository = SampleAutoAssignmentRepository(
        Database(session),
        category="测试",
        batch_limit=1,
        activation_at=datetime(2026, 9, 14, tzinfo=UTC),
    )
    roster = [
        BdWorkload(
            "李鸿程",
            bd_id="rec-bd",
            recipient_open_id="ou-bd",
            current_pending=1,
            total_assigned=2,
            assigned_today=2,
            level_counts={"L3": 1, "L2": 1},
            last_received_levels=frozenset({"L2", "L3"}),
        )
    ]

    async with repository.transaction(request) as transaction:
        workloads = await transaction.load_workloads(roster)

    assert workloads[0].current_pending == 1
    assert workloads[0].total_assigned == 2
    assert workloads[0].level_counts == {"L3": 1, "L2": 1}
    assert workloads[0].assigned_today == 2
    assert workloads[0].last_received_levels == frozenset({"L2", "L3"})
    assert len(session.statements) == 3


@pytest.mark.asyncio
async def test_manual_l3_reassignment_rotates_away_from_new_bd() -> None:
    request = _request()
    manual_reassignment_at = datetime(2026, 9, 15, 2, tzinfo=UTC)
    session = Session(workflow=SimpleNamespace(assigned_bd_name=None))
    repository = SampleAutoAssignmentRepository(
        Database(session),
        category="测试",
        batch_limit=1,
        activation_at=datetime(2026, 9, 14, tzinfo=UTC),
    )
    roster = (
        BdWorkload("BD A", bd_id="rec-a", recipient_open_id="ou-a"),
        BdWorkload(
            "BD B",
            bd_id="rec-b",
            recipient_open_id="ou-b",
            total_assigned=1,
            level_counts={"L3": 1},
            last_assigned_at=manual_reassignment_at,
            last_assigned_level="L3",
            last_received_levels=frozenset({"L3"}),
        ),
    )

    async with repository.transaction(request) as transaction:
        workloads = await transaction.load_workloads(roster)
    decision = select_bd_for_level("L3", workloads, category="测试")

    assert workloads[1].last_received_levels == frozenset({"L3"})
    assert decision.assigned_bd_name == "BD A"
