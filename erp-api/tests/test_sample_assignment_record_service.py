from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from erp_api.services.feishu_sample_record_snapshot import (
    FeishuListedRecord,
    FeishuRecordSnapshot,
)
from erp_api.services.sample_assignment_record_fields import (
    ASSIGNMENT_RECORD_SCHEMA,
    assignment_shop_name,
    record_fields,
)
from erp_api.services.sample_assignment_record_service import (
    SampleAssignmentRecordService,
)


class Result:
    def __init__(self, rows) -> None:
        self.rows = rows

    def all(self):
        return self.rows


class Session:
    def __init__(self, rows, obsolete=(), locked_outbox=None) -> None:
        self.rows = rows
        self.obsolete = obsolete
        self.locked_outbox = locked_outbox
        self.statements = []
        self.commit_count = 0

    async def execute(self, statement):
        self.statements.append(statement)
        return Result(self.rows)

    async def scalars(self, statement):
        self.statements.append(statement)
        return SimpleNamespace(all=lambda: list(self.obsolete))

    async def scalar(self, statement):
        self.statements.append(statement)
        if self.locked_outbox is not None:
            return self.locked_outbox
        values = set(statement.compile(dialect=postgresql.dialect()).params.values())
        return next((row[0] for row in self.rows if row[0].id in values), None)

    async def commit(self):
        self.commit_count += 1


class Database:
    def __init__(self, session) -> None:
        self.session = session

    @asynccontextmanager
    async def system_session_factory(self):
        yield self.session


class Client:
    def __init__(self, records=(), record_by_id=None) -> None:
        self.records = records
        self.record_by_id = record_by_id or {}
        self.creates = []
        self.updates = []
        self.deletes = []
        self.list_calls = 0
        self.batch_creates = []
        self.batch_updates = []

    async def list_record_snapshots(self):
        self.list_calls += 1
        return self.records

    async def get_record(self, record_id):
        if record_id in self.record_by_id:
            return self.record_by_id[record_id]
        for record in self.records:
            if record.record_id == record_id:
                return record.snapshot.fields
        raise AssertionError(f"Unexpected record read: {record_id}")

    async def create_assignment_record(self, fields):
        self.creates.append(fields)
        return "rec-created"

    async def update_assignment_record(self, record_id, fields):
        self.updates.append((record_id, fields))

    async def batch_create_assignment_records(self, rows):
        self.batch_creates.append(list(rows))
        created = {}
        for fields in rows:
            self.creates.append(fields)
            record_id = (
                "rec-created"
                if len(self.creates) == 1
                else f"rec-created-{len(self.creates)}"
            )
            created[fields["分配编号"]] = record_id
            self.record_by_id[record_id] = fields
        return created

    async def batch_update_assignment_records(self, rows):
        self.batch_updates.append(list(rows))
        self.updates.extend(rows)
        return tuple(record_id for record_id, _fields in rows)

    async def delete_assignment_record(self, record_id):
        self.deletes.append(record_id)


def _row(*, status="pending", sent_at=None, assignment_notice=None):
    now = datetime(2026, 9, 10, 3, tzinfo=UTC)
    event_id = uuid4()
    payload = {
        "assigned_bd_name": "吴洵涛",
        "source_event_id": "bd-auto:bd-v1-smoke:application-id",
    }
    if assignment_notice:
        payload["assignment_notice"] = assignment_notice
    outbox = SimpleNamespace(
        id=event_id,
        payload=payload,
        status=status,
        sent_at=sent_at,
        created_at=now,
    )
    application = SimpleNamespace(
        platform_application_id="9606903440947327882",
        raw_payload={"source_item_ids": ["application-1"]},
        creator_nickname="达人一",
        creator_username="creator-one",
        creator_open_id="internal-open-id",
        sku_id="sku-1",
        product_id="product-1",
    )
    workflow = SimpleNamespace(assigned_bd_name="吴洵涛", assigned_at=now)
    shop = SimpleNamespace(shop_name="Akeleo Toys")
    return event_id, (outbox, application, workflow, shop)


def test_assignment_record_uses_creator_account_and_shop_name() -> None:
    _event_id, row = _row()

    fields = record_fields(row)

    assert fields["达人ID"] == "creator-one"
    assert fields["店铺名称"] == "Akeleo Toys"
    assert "达人昵称" not in fields


def test_assignment_shop_name_adds_business_shop_suffix() -> None:
    shop = SimpleNamespace(
        id=__import__("uuid").UUID("eb7678c2-67d6-5446-85f0-dc8fba9b75d6"),
        shop_name="fanfu toy tool",
    )

    assert assignment_shop_name(shop) == "fanfu toy tool（跨境3）"


def test_assignment_record_schema_places_shop_after_creator_id() -> None:
    names = [name for name, _field_type in ASSIGNMENT_RECORD_SCHEMA]

    assert names.index("店铺名称") == names.index("达人ID") + 1


def test_assignment_record_writes_level_rotation_conflict_reminder() -> None:
    _event_id, row = _row(assignment_notice="same_creator_level_rotation_conflict")

    fields = record_fields(row)

    assert fields["分配提醒"] == "同达人原BD与本店本等级轮转冲突，已改分当前BD"


def test_assignment_record_writes_level_imbalance_reminder() -> None:
    _event_id, row = _row(assignment_notice="same_creator_level_imbalance")

    fields = record_fields(row)

    assert fields["分配提醒"] == "同达人原BD的本店本等级数量偏高，已均衡改分"


@pytest.mark.asyncio
async def test_creates_idempotent_assignment_record_from_auto_outbox() -> None:
    event_id, row = _row()
    session = Session([row])
    client = Client()
    notifications = []

    async def notify_change():
        notifications.append(True)

    activation_at = datetime(2026, 9, 14, 9, 37, tzinfo=UTC)
    service = SampleAssignmentRecordService(
        Database(session),
        client,
        activation_at=activation_at,
        change_notifier=notify_change,
    )

    result = await service.sync(
        tenant_id=uuid4(), shop_id=uuid4(), outbox_ids=frozenset({event_id})
    )

    assert result.created_count == 1
    assert result.updated_count == 0
    assert notifications == [True]
    assert client.creates[0]["分配编号"] == str(event_id)
    assert client.creates[0]["申请编号"] == "9606903440947327882"
    assert client.creates[0]["达人ID"] == "creator-one"
    assert client.creates[0]["店铺名称"] == "Akeleo Toys"
    assert client.creates[0]["分配BD"] == "吴洵涛"
    assert client.creates[0]["通知状态"] == "待通知"
    assert client.creates[0]["备注"].startswith("current-application:")
    assert len(client.batch_creates) == 1
    sql = str(session.statements[0].compile(dialect=postgresql.dialect()))
    assert "sample_notification_outbox.payload" in sql
    assert "sample_notification_outbox.id IN" in sql
    assert "sample_applications.is_current_projection IS true" in sql
    assert "sample_notification_outbox.status !=" in sql
    assert (
        "sample_notification_outbox.assignment_version = "
        "sample_application_workflows.assignment_version"
    ) in sql
    assert "sample_application_workflows.assigned_bd_name IS NOT NULL" in sql
    assert "IS NOT true" in sql
    assert "sample_applications.tiktok_applied_at >=" in sql
    assert "sample_applications.first_seen_at >=" in sql
    assert "sample_applications.source_type" in sql
    assert "JOIN shops" in sql
    compiled = session.statements[0].compile(dialect=postgresql.dialect())
    assert "manual_assignment_deleted" in compiled.params.values()
    assert activation_at in compiled.params.values()
    assert "creator-group:%" not in compiled.params.values()


@pytest.mark.asyncio
async def test_persists_created_record_id_before_eventual_list_visibility() -> None:
    event_id, row = _row()
    session = Session([row])
    client = Client()
    service = SampleAssignmentRecordService(
        Database(session),
        client,
        activation_at=datetime(2026, 9, 14, 9, 37, tzinfo=UTC),
    )

    first = await service.sync(
        tenant_id=uuid4(), shop_id=uuid4(), outbox_ids=frozenset({event_id})
    )
    second = await service.sync(
        tenant_id=uuid4(), shop_id=uuid4(), outbox_ids=frozenset({event_id})
    )

    assert first.created_count == 1
    assert second.created_count == 0
    assert second.updated_count == 1
    assert len(client.creates) == 1
    assert client.list_calls == 1
    assert client.updates[0][0] == "rec-created"
    assert len(client.batch_updates) == 1
    assert row[0].payload["assignment_record_id"] == "rec-created"
    assert session.commit_count == 1


@pytest.mark.asyncio
async def test_rechecks_persisted_record_id_under_row_lock_before_post() -> None:
    event_id, row = _row()
    locked_outbox = SimpleNamespace(
        id=event_id,
        payload={**row[0].payload, "assignment_record_id": "rec-raced"},
    )
    session = Session([row], locked_outbox=locked_outbox)
    client = Client(record_by_id={"rec-raced": record_fields(row)})
    service = SampleAssignmentRecordService(
        Database(session),
        client,
        activation_at=datetime(2026, 9, 14, 9, 37, tzinfo=UTC),
    )

    result = await service.sync(
        tenant_id=uuid4(), shop_id=uuid4(), outbox_ids=frozenset({event_id})
    )

    assert result.created_count == 0
    assert result.updated_count == 1
    assert client.creates == []
    assert client.updates[0][0] == "rec-raced"
    lock_sql = str(session.statements[-1].compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE" in lock_sql


@pytest.mark.asyncio
async def test_blocks_duplicate_creator_record_in_same_shop_without_deleting() -> None:
    event_id, row = _row()
    older = FeishuListedRecord(
        "rec-older",
        FeishuRecordSnapshot(
            {
                "分配编号": str(uuid4()),
                "达人ID": "creator-one",
                "店铺名称": "Akeleo Toys",
                "分配时间": 1,
            }
        ),
    )
    newer = FeishuListedRecord(
        "rec-newer",
        FeishuRecordSnapshot(
            {
                "分配编号": str(uuid4()),
                "达人ID": "creator-one",
                "店铺名称": "Akeleo Toys",
                "分配时间": 2,
            }
        ),
    )
    session = Session([row])
    client = Client(records=(older, newer))
    service = SampleAssignmentRecordService(
        Database(session),
        client,
        activation_at=datetime(2026, 9, 14, 9, 37, tzinfo=UTC),
    )

    with pytest.raises(RuntimeError, match="creator and shop is duplicated"):
        await service.sync(
            tenant_id=uuid4(),
            shop_id=uuid4(),
            outbox_ids=frozenset({event_id}),
        )

    assert client.deletes == []


@pytest.mark.asyncio
async def test_same_creator_in_different_shops_is_not_deleted() -> None:
    records = tuple(
        FeishuListedRecord(
            f"rec-{index}",
            FeishuRecordSnapshot(
                {
                    "分配编号": str(uuid4()),
                    "达人ID": "creator-one",
                    "店铺名称": shop,
                    "分配时间": index,
                }
            ),
        )
        for index, shop in enumerate(("Akeleo Toys", "fanfu toy tool"), start=1)
    )
    client = Client(records=records)
    service = SampleAssignmentRecordService(
        Database(Session([])),
        client,
        activation_at=datetime(2026, 9, 14, 9, 37, tzinfo=UTC),
    )

    await service.sync(tenant_id=uuid4(), shop_id=uuid4())

    assert client.deletes == []


@pytest.mark.asyncio
async def test_limits_assignment_records_to_selected_applications() -> None:
    _event_id, row = _row()
    application_id = uuid4()
    session = Session([row])
    service = SampleAssignmentRecordService(
        Database(session),
        Client(),
        activation_at=datetime(2026, 9, 14, 9, 37, tzinfo=UTC),
    )

    await service.sync(
        tenant_id=uuid4(),
        shop_id=uuid4(),
        application_ids=frozenset({application_id}),
    )

    sql = str(session.statements[0].compile(dialect=postgresql.dialect()))
    assert "sample_applications.id IN" in sql


@pytest.mark.asyncio
async def test_updates_existing_record_after_notification_is_sent() -> None:
    sent_at = datetime(2026, 9, 10, 3, 5, tzinfo=UTC)
    _event_id, row = _row(status="sent", sent_at=sent_at)
    existing = FeishuListedRecord(
        "rec-existing",
        FeishuRecordSnapshot(record_fields(row)),
    )
    client = Client((existing,))
    service = SampleAssignmentRecordService(
        Database(Session([row])),
        client,
        activation_at=datetime(2026, 9, 14, 9, 37, tzinfo=UTC),
    )

    result = await service.sync(tenant_id=uuid4(), shop_id=uuid4())

    assert result.created_count == 0
    assert result.updated_count == 1
    assert client.updates[0][0] == "rec-existing"
    assert client.updates[0][1]["通知状态"] == "已通知"
    assert client.updates[0][1]["通知时间"] == int(sent_at.timestamp() * 1000)


@pytest.mark.asyncio
async def test_blocks_second_bd_from_overwriting_first_creator_assignment() -> None:
    first_id, first = _row(status="sent")
    _second_id, second = _row(status="sent")
    second[1].platform_application_id = "second-application"
    second[0].payload["assigned_bd_name"] = "other-bd"
    second[2].assigned_bd_name = "other-bd"
    second[2].assigned_at = datetime(2026, 9, 12, 3, tzinfo=UTC)
    first_record = FeishuListedRecord(
        "rec-first", FeishuRecordSnapshot(record_fields(first))
    )
    client = Client((first_record,))
    service = SampleAssignmentRecordService(
        Database(Session([second])),
        client,
        activation_at=datetime(2026, 9, 14, 9, 37, tzinfo=UTC),
    )

    with pytest.raises(RuntimeError, match="seven-day owner conflict"):
        await service.sync(tenant_id=uuid4(), shop_id=uuid4())

    assert client.updates == []
    assert client.creates == []
    assert first_id != second[0].id


@pytest.mark.asyncio
async def test_blocks_misbound_stored_record_from_overwriting_first_bd() -> None:
    _first_id, first = _row(status="sent")
    _second_id, second = _row(status="sent")
    second[1].platform_application_id = "second-application"
    second[0].payload["assigned_bd_name"] = "other-bd"
    second[0].payload["assignment_record_id"] = "rec-first"
    second[2].assigned_bd_name = "other-bd"
    second[2].assigned_at = datetime(2026, 9, 12, 3, tzinfo=UTC)
    client = Client(record_by_id={"rec-first": record_fields(first)})
    service = SampleAssignmentRecordService(
        Database(Session([second])),
        client,
        activation_at=datetime(2026, 9, 14, 9, 37, tzinfo=UTC),
    )

    with pytest.raises(RuntimeError, match="seven-day owner conflict"):
        await service.sync(tenant_id=uuid4(), shop_id=uuid4())

    assert client.updates == []


@pytest.mark.asyncio
async def test_multiple_assignment_records_create_in_one_batch() -> None:
    first_id, first = _row()
    second_id, second = _row()
    second[1].creator_username = "creator-two"
    second[1].creator_open_id = "second-open-id"
    session = Session([first, second])
    client = Client()
    service = SampleAssignmentRecordService(
        Database(session),
        client,
        activation_at=datetime(2026, 9, 14, 9, 37, tzinfo=UTC),
    )

    result = await service.sync(
        tenant_id=uuid4(), shop_id=uuid4(), outbox_ids=frozenset({first_id, second_id})
    )

    assert result.created_count == 2
    assert len(client.batch_creates) == 1
    assert len(client.batch_creates[0]) == 2
    assert first[0].payload["assignment_record_id"]
    assert second[0].payload["assignment_record_id"]
    assert session.commit_count == 1


@pytest.mark.asyncio
async def test_multiple_existing_assignment_records_update_in_one_batch() -> None:
    first_id, first = _row()
    second_id, second = _row()
    second[1].creator_username = "creator-two"
    second[1].creator_open_id = "second-open-id"
    first[0].payload["assignment_record_id"] = "rec-1"
    second[0].payload["assignment_record_id"] = "rec-2"
    session = Session([first, second])
    client = Client(
        record_by_id={"rec-1": record_fields(first), "rec-2": record_fields(second)}
    )
    service = SampleAssignmentRecordService(
        Database(session),
        client,
        activation_at=datetime(2026, 9, 14, 9, 37, tzinfo=UTC),
    )

    result = await service.sync(
        tenant_id=uuid4(), shop_id=uuid4(), outbox_ids=frozenset({first_id, second_id})
    )

    assert result.updated_count == 2
    assert len(client.batch_updates) == 1
    assert {item[0] for item in client.batch_updates[0]} == {"rec-1", "rec-2"}
    assert session.commit_count == 0


@pytest.mark.asyncio
async def test_rejects_duplicate_assignment_numbers_in_feishu() -> None:
    event_id, row = _row()
    records = tuple(
        FeishuListedRecord(
            f"rec-{index}", FeishuRecordSnapshot({"分配编号": str(event_id)})
        )
        for index in range(2)
    )
    service = SampleAssignmentRecordService(
        Database(Session([row])),
        Client(records),
        activation_at=datetime(2026, 9, 14, 9, 37, tzinfo=UTC),
    )

    with pytest.raises(RuntimeError, match="duplicated"):
        await service.sync(tenant_id=uuid4(), shop_id=uuid4())


@pytest.mark.asyncio
async def test_unrelated_duplicate_does_not_block_assignment_record_sync() -> None:
    event_id, row = _row()
    duplicate_number = str(uuid4())
    records = tuple(
        FeishuListedRecord(
            f"rec-{index}",
            FeishuRecordSnapshot(
                {
                    "分配编号": duplicate_number,
                    "达人ID": "unrelated-creator",
                    "店铺名称": "fanfu toy tool（跨境3）",
                }
            ),
        )
        for index in range(2)
    )
    client = Client(records)
    service = SampleAssignmentRecordService(
        Database(Session([row])),
        client,
        activation_at=datetime(2026, 9, 14, 9, 37, tzinfo=UTC),
    )

    result = await service.sync(
        tenant_id=uuid4(), shop_id=uuid4(), outbox_ids=frozenset({event_id})
    )

    assert result.created_count == 1
    assert client.creates[0]["分配编号"] == str(event_id)
