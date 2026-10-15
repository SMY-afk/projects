from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from erp_api.services.sample_auto_assignment_feishu_service import (
    SampleAutoAssignmentFeishuService,
)


class Result:
    def __init__(self, rows) -> None:
        self.rows = rows

    def all(self):
        return self.rows


class Session:
    def __init__(self, *, rows=(), workflow=None) -> None:
        self.rows = rows
        self.workflow = workflow
        self.statements = []
        self.commits = 0

    async def execute(self, statement):
        self.statements.append(statement)
        return Result(self.rows)

    async def scalar(self, statement):
        self.statements.append(statement)
        return self.workflow

    async def scalars(self, statement):
        self.statements.append(statement)
        workflows = (
            self.workflow if isinstance(self.workflow, list) else [self.workflow]
        )
        return Result(workflows)

    async def commit(self):
        self.commits += 1


class Database:
    def __init__(self, sessions) -> None:
        self.sessions = iter(sessions)

    @asynccontextmanager
    async def system_session_factory(self):
        yield next(self.sessions)


class Client:
    def __init__(self, fields=None) -> None:
        self.updates = []
        self.batches = []
        self.fields = fields or {}

    async def get_record(self, record_id):
        return self.fields[record_id]

    async def batch_update_business_fields(self, records):
        self.batches.append(list(records))
        self.updates.extend(records)
        return tuple(record_id for record_id, _fields in records)


@pytest.mark.asyncio
async def test_projects_auto_assignment_and_marks_success() -> None:
    tenant_id, shop_id, workflow_id = uuid4(), uuid4(), uuid4()
    occurred_at = datetime(2026, 9, 10, tzinfo=UTC)
    list_session = Session(
        rows=[
            SimpleNamespace(
                id=workflow_id,
                feishu_record_id="rec-sample",
                assigned_bd_name="李鸿程",
                processing_status="待处理",
                occurred_at=occurred_at,
            )
        ]
    )
    workflow = SimpleNamespace(id=workflow_id, feishu_updated_at=None)
    mark_session = Session(workflow=workflow)
    client = Client()
    service = SampleAutoAssignmentFeishuService(
        Database([list_session, mark_session]), client
    )

    result = await service.sync(tenant_id=tenant_id, shop_id=shop_id)

    assert result.updated_count == 1
    assert client.updates == [
        ("rec-sample", {"分配BD": "李鸿程", "处理状态": "待处理"})
    ]
    assert len(client.batches) == 1
    assert workflow.feishu_updated_at >= occurred_at
    assert mark_session.commits == 1
    sql = str(list_session.statements[0].compile(dialect=postgresql.dialect()))
    assert "sample_application_events.event_type" in sql
    assert "sample_application_workflows.feishu_updated_at" in sql
    parameters = list_session.statements[0].compile(dialect=postgresql.dialect()).params
    assert set(parameters["event_type_1"]) == {
        "bd_auto_assigned",
        "bd_assignment_projection_migrated",
    }


@pytest.mark.asyncio
async def test_projection_routes_update_to_target_shop_table() -> None:
    tenant_id, shop_id, workflow_id = uuid4(), uuid4(), uuid4()
    list_session = Session(
        rows=[
            SimpleNamespace(
                id=workflow_id,
                feishu_record_id="rec-sample",
                assigned_bd_name="BD A",
                processing_status="pending",
                occurred_at=datetime(2026, 9, 10, tzinfo=UTC),
            )
        ]
    )
    shop_client = Client()

    class Router:
        def for_shop(self, actual_shop_id):
            assert actual_shop_id == shop_id
            return shop_client

    service = SampleAutoAssignmentFeishuService(
        Database([list_session, Session(workflow=SimpleNamespace(id=workflow_id))]),
        Router(),
    )

    result = await service.sync(tenant_id=tenant_id, shop_id=shop_id)

    assert result.updated_count == 1
    assert shop_client.updates[0][0] == "rec-sample"


@pytest.mark.asyncio
async def test_multiple_assignment_updates_share_one_feishu_batch() -> None:
    tenant_id, shop_id = uuid4(), uuid4()
    occurred_at = datetime(2026, 9, 10, tzinfo=UTC)
    first_id, second_id = uuid4(), uuid4()
    rows = [
        SimpleNamespace(
            id=workflow_id,
            feishu_record_id=f"rec-{index}",
            assigned_bd_name=f"BD {index}",
            processing_status="待处理",
            occurred_at=occurred_at,
        )
        for index, workflow_id in enumerate((first_id, second_id), start=1)
    ]
    workflows = [
        SimpleNamespace(id=workflow_id, feishu_updated_at=None)
        for workflow_id in (first_id, second_id)
    ]
    mark_session = Session(workflow=workflows)
    client = Client()
    service = SampleAutoAssignmentFeishuService(
        Database([Session(rows=rows), mark_session]), client
    )

    result = await service.sync(tenant_id=tenant_id, shop_id=shop_id)

    assert result.updated_count == 2
    assert len(client.batches) == 1
    assert len(client.batches[0]) == 2
    assert all(row.feishu_updated_at >= occurred_at for row in workflows)
    assert mark_session.commits == 1


def test_projection_requires_bounded_limit() -> None:
    with pytest.raises(ValueError, match="limit"):
        SampleAutoAssignmentFeishuService(object(), object(), limit=101)


@pytest.mark.asyncio
async def test_final_projection_repairs_feishu_row_cleared_by_later_sync() -> None:
    tenant_id, shop_id, workflow_id = uuid4(), uuid4(), uuid4()
    occurred_at = datetime(2026, 10, 6, tzinfo=UTC)
    row = SimpleNamespace(
        id=workflow_id,
        feishu_record_id="rec-sample",
        assigned_bd_name="example-24ffed966710",
        processing_status="待处理",
        occurred_at=occurred_at,
    )
    workflow = SimpleNamespace(id=workflow_id, feishu_updated_at=occurred_at)
    client = Client(fields={"rec-sample": {"分配BD": None, "处理状态": "待处理"}})
    service = SampleAutoAssignmentFeishuService(
        Database([Session(rows=[row]), Session(workflow=workflow)]), client
    )

    result = await service.sync(
        tenant_id=tenant_id, shop_id=shop_id, verify_current=True
    )

    assert result.updated_count == 1
    assert client.updates == [
        ("rec-sample", {"分配BD": "example-24ffed966710", "处理状态": "待处理"})
    ]
