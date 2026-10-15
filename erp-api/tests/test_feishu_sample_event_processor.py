from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from erp_api.services.feishu_sample_client import FeishuRecordSnapshot
from erp_api.services.feishu_sample_event_processor import (
    FeishuBusinessEventProcessor,
    FeishuSampleEventProcessingError,
    FeishuSampleEventProcessor,
    record_event_idempotency_key,
)
from erp_api.services.feishu_sample_event_receiver import (
    FeishuEventPayloadError,
    FeishuEventReceipt,
    FeishuRecordEdit,
)
from erp_api.services.feishu_sample_fields import FeishuFieldMetadata


class FakeFeishuClient:
    def __init__(self) -> None:
        self.metadata_calls = 0
        self.record_calls: list[str] = []

    async def validate_required_fields(self, required_fields):
        self.metadata_calls += 1
        fields = {
            "分配BD": FeishuFieldMetadata("fld-bd", "分配BD", 11, False),
            "处理状态": FeishuFieldMetadata("fld-status", "处理状态", 3, False),
            "处理结果": FeishuFieldMetadata("fld-result", "处理结果", 1, False),
            "备注": FeishuFieldMetadata("fld-note", "备注", 1, False),
        }
        assert set(required_fields) <= set(fields)
        return fields

    async def get_record_snapshot(self, record_id: str):
        self.record_calls.append(record_id)
        return FeishuRecordSnapshot(
            fields={
                "分配BD": [{"id": "ou-bd", "name": "BD B"}],
                "处理状态": "跟进中",
                "处理结果": "Accepted",
                "备注": "Updated",
                "TK申请状态": "SHIPPED",
            },
            modifier_id="ou-user",
            modifier_name="Test User",
            modified_at=datetime(2027, 1, 15, 8, tzinfo=UTC),
        )


class FakeRepository:
    def __init__(self, statuses: list[str] | None = None) -> None:
        self.statuses = statuses or ["applied"]
        self.calls: list[dict[str, object]] = []

    async def apply_feishu_business_fields(self, **kwargs):
        self.calls.append(kwargs)
        return self.statuses.pop(0)


def _receipt(*edits: FeishuRecordEdit, **overrides) -> FeishuEventReceipt:
    values = {
        "kind": "event",
        "event_id": "event-1",
        "event_type": "drive.file.bitable_record_changed_v1",
        "occurred_at": datetime(2026, 9, 10, tzinfo=UTC),
        "file_token": "base-token",
        "table_id": "table-id",
        "operator_id": "ou-user",
        "record_edits": tuple(edits),
    }
    values.update(overrides)
    return FeishuEventReceipt(**values)


def _processor(repository=None, client=None) -> FeishuSampleEventProcessor:
    return FeishuSampleEventProcessor(
        repository or FakeRepository(),
        client or FakeFeishuClient(),
        base_token="base-token",
        table_id="table-id",
    )


def test_business_event_router_dispatches_sample_and_assignment_changes() -> None:
    changed = []

    async def notify():
        changed.append(True)

    repository = FakeRepository()
    client = FakeFeishuClient()
    router = FeishuBusinessEventProcessor(
        base_token="base-token",
        sample_processors={"table-id": _processor(repository, client)},
        assignment_table_id="assignment-table",
        assignment_notifier=notify,
    )

    sample = asyncio.run(
        router.process(_receipt(FeishuRecordEdit("rec-1", frozenset({"fld-bd"}))))
    )
    assignment = asyncio.run(router.process(_receipt(table_id="assignment-table")))

    assert sample.applied_count == 1
    assert assignment.ignored_count == 1
    assert changed == [True]
    with pytest.raises(FeishuEventPayloadError):
        asyncio.run(router.process(_receipt(table_id="other-table")))


def test_processor_reads_mapped_record_and_writes_only_changed_business_fields() -> (
    None
):
    repository = FakeRepository()
    client = FakeFeishuClient()
    processor = _processor(repository, client)
    receipt = _receipt(FeishuRecordEdit("rec-1", frozenset({"fld-bd", "fld-system"})))

    result = asyncio.run(processor.process(receipt))

    assert result.applied_count == 1
    assert client.record_calls == ["rec-1"]
    assert repository.calls[0]["record_id"] == "rec-1"
    assert repository.calls[0]["fields"] == {"分配BD": "BD B"}
    assert repository.calls[0]["event_source"] == "feishu_callback"
    assert repository.calls[0]["actor_id"] == "ou-user"
    assert repository.calls[0]["actor_name"] == "Test User"
    assert repository.calls[0]["assignment_recipient_open_id"] == "ou-bd"


def test_processor_ignores_non_business_field_actions_without_reading_record() -> None:
    repository = FakeRepository()
    client = FakeFeishuClient()
    processor = _processor(repository, client)

    result = asyncio.run(
        processor.process(
            _receipt(FeishuRecordEdit("rec-1", frozenset({"fld-system"})))
        )
    )

    assert result.ignored_count == 1
    assert client.record_calls == []
    assert repository.calls == []


def test_processor_rejects_multiple_bd_users() -> None:
    client = FakeFeishuClient()

    async def multiple_bd_record(record_id: str):
        snapshot = await FakeFeishuClient().get_record_snapshot(record_id)
        return FeishuRecordSnapshot(
            fields={**snapshot.fields, "分配BD": [{"name": "A"}, {"name": "B"}]}
        )

    client.get_record_snapshot = multiple_bd_record
    with pytest.raises(FeishuSampleEventProcessingError, match="field value"):
        asyncio.run(
            _processor(client=client).process(
                _receipt(FeishuRecordEdit("rec-1", frozenset({"fld-bd"})))
            )
        )


def test_processor_caches_field_metadata_and_reports_duplicate_and_unchanged() -> None:
    repository = FakeRepository(["duplicate", "unchanged"])
    client = FakeFeishuClient()
    processor = _processor(repository, client)
    receipt = _receipt(FeishuRecordEdit("rec-1", frozenset({"fld-note"})))

    first = asyncio.run(processor.process(receipt))
    second = asyncio.run(processor.process(receipt))

    assert first.duplicate_count == 1
    assert second.unchanged_count == 1
    assert client.metadata_calls == 1


def test_processor_rejects_events_from_another_base_or_table() -> None:
    processor = _processor()

    with pytest.raises(FeishuEventPayloadError, match="target"):
        asyncio.run(processor.process(_receipt(file_token="other-base")))
    with pytest.raises(FeishuEventPayloadError, match="target"):
        asyncio.run(processor.process(_receipt(table_id="other-table")))


def test_multi_record_event_uses_stable_distinct_idempotency_keys() -> None:
    first = record_event_idempotency_key("event-1", "rec-1", record_count=2)
    second = record_event_idempotency_key("event-1", "rec-2", record_count=2)

    assert first == record_event_idempotency_key("event-1", "rec-1", record_count=2)
    assert first != second
    assert len(first) <= 255
    assert record_event_idempotency_key("event-1", "rec-1", record_count=1) == (
        "event-1"
    )
