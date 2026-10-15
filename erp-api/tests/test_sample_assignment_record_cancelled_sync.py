from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from erp_api.services.sample_assignment_record_service import (
    SampleAssignmentRecordService,
)


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _Session:
    def __init__(self, row):
        self.row = row
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return _Result([self.row])

    async def scalar(self, statement):
        self.statements.append(statement)
        return self.row[0]

    async def commit(self):
        raise AssertionError("Cancelled records must not be recreated or rebound.")


class _Database:
    def __init__(self, session):
        self.session = session

    @asynccontextmanager
    async def system_session_factory(self):
        yield self.session


class _Client:
    def __init__(self, fields):
        self.fields = fields
        self.updates = []

    async def get_record(self, record_id):
        assert record_id == "rec-existing"
        return self.fields

    async def batch_update_assignment_records(self, rows):
        self.updates.extend(rows)
        return tuple(record_id for record_id, _fields in rows)


@pytest.mark.asyncio
async def test_cancelled_persisted_assignment_updates_existing_feishu_row() -> None:
    now = datetime(2026, 10, 8, 11, tzinfo=UTC)
    outbox = SimpleNamespace(
        id=uuid4(),
        payload={
            "assigned_bd_name": "朝阳",
            "source_event_id": "bd-auto:bd-v17-sample-image-required:application",
            "assignment_record_id": "rec-existing",
        },
        status="cancelled",
        sent_at=None,
        created_at=now,
    )
    application = SimpleNamespace(
        platform_application_id="application",
        raw_payload={},
        creator_username="creator",
        sku_id="sku",
        product_id="product",
    )
    workflow = SimpleNamespace(assigned_bd_name="朝阳", assigned_at=now)
    shop = SimpleNamespace(shop_name="fanfu toy tool")
    row = (outbox, application, workflow, shop)
    existing = {
        "分配编号": str(outbox.id),
        "申请编号": "application",
        "达人ID": "creator",
        "店铺名称": "fanfu toy tool",
        "样品编号": "sku",
        "分配BD": "朝阳",
        "分配提醒": "",
        "分配人": "ERP自动分配",
        "分配时间": int(now.timestamp() * 1000),
        "通知状态": "待通知",
        "备注": "current-application:bd-auto:bd-v17-sample-image-required:application",
    }
    session = _Session(row)
    client = _Client(existing)
    service = SampleAssignmentRecordService(
        _Database(session),
        client,
        activation_at=datetime(2026, 9, 14, 9, 37, tzinfo=UTC),
    )

    result = await service.sync(tenant_id=uuid4(), shop_id=uuid4())

    assert result.created_count == 0
    assert result.updated_count == 1
    assert client.updates[0][0] == "rec-existing"
    assert client.updates[0][1]["通知状态"] == "已取消"
    compiled = session.statements[0].compile(dialect=postgresql.dialect())
    assert "assignment_record_id" in compiled.params.values()
