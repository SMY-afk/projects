from datetime import UTC, datetime, timedelta

import pytest

from erp_api.services.feishu_sample_record_snapshot import (
    FeishuListedRecord,
    FeishuRecordSnapshot,
)
from erp_api.services.sample_feishu_mapping_repository import SampleFeishuPollState
from erp_api.services.sample_feishu_reverse_poll_service import (
    FeishuSampleReversePollError,
    SampleFeishuReversePollService,
)


class FakeClient:
    def __init__(self, records):
        self.records = records
        self.modified_dates = []

    async def list_record_snapshots(self, *, modified_since_date=None):
        self.modified_dates.append(modified_since_date)
        return self.records


class FakeMappingRepository:
    def __init__(self, states):
        self.states = states
        self.calls = []

    async def list_poll_states(self, record_ids):
        self.calls.append(tuple(record_ids))
        return self.states


class FakeApplicationRepository:
    def __init__(self, statuses=None):
        self.statuses = statuses or ["applied"]
        self.calls = []

    async def apply_feishu_business_fields(self, **kwargs):
        self.calls.append(kwargs)
        return self.statuses.pop(0)


class FakeRecipientProvider:
    async def list_recipient_open_ids(self):
        return {"BD B": "ou-bd"}


def _record(record_id, modified_at, fields=None):
    return FeishuListedRecord(
        record_id,
        FeishuRecordSnapshot(
            fields=fields or {"备注": "Updated"},
            modifier_id="ou-user",
            modifier_name="Test User",
            modified_at=modified_at,
        ),
    )


def _state(updated_at, **fields):
    return SampleFeishuPollState(
        updated_at,
        {
            "分配BD": fields.get("assigned_bd_name"),
            "处理状态": fields.get("processing_status"),
            "处理结果": fields.get("processing_result"),
            "备注": fields.get("business_note"),
        },
    )


@pytest.mark.asyncio
async def test_reverse_poll_applies_only_newer_mapped_business_records() -> None:
    now = datetime(2026, 9, 10, 9, tzinfo=UTC)
    records = (
        _record(
            "rec-new",
            now,
            {"分配BD": [{"id": "ou-bd", "name": "BD B"}], "备注": "New"},
        ),
        _record("rec-old", now - timedelta(minutes=10)),
        _record("rec-unmapped", now),
    )
    mappings = FakeMappingRepository(
        {
            "rec-new": _state(now - timedelta(minutes=1)),
            "rec-old": _state(now - timedelta(minutes=1)),
        }
    )
    applications = FakeApplicationRepository()
    service = SampleFeishuReversePollService(
        applications, mappings, (FakeClient(records),)
    )

    result = await service.poll()

    assert result.applied_count == 1
    assert result.skipped_count == 1
    assert result.unmapped_count == 1
    assert applications.calls[0]["record_id"] == "rec-new"
    assert applications.calls[0]["fields"] == {"分配BD": "BD B", "备注": "New"}
    assert applications.calls[0]["assignment_recipient_open_id"] == "ou-bd"
    assert applications.calls[0]["event_source"] == "feishu_poll"
    assert applications.calls[0]["occurred_at"] == now


@pytest.mark.asyncio
async def test_reverse_poll_hourly_uses_overlap_and_full_audit_reads_all() -> None:
    client = FakeClient(())
    service = SampleFeishuReversePollService(
        FakeApplicationRepository(), FakeMappingRepository({}), (client,)
    )
    now = datetime(2026, 10, 4, 9, tzinfo=UTC)

    await service.poll(full_scan=False, now=now)
    await service.poll(full_scan=True, now=now)

    assert client.modified_dates == ["2026-10-02", None]


@pytest.mark.asyncio
async def test_reverse_poll_requires_record_modified_time() -> None:
    service = SampleFeishuReversePollService(
        FakeApplicationRepository(),
        FakeMappingRepository({"rec-1": _state(None)}),
        (FakeClient((_record("rec-1", None),)),),
    )

    with pytest.raises(FeishuSampleReversePollError, match="modified time"):
        await service.poll()


@pytest.mark.asyncio
async def test_reverse_poll_reads_every_configured_feishu_table() -> None:
    now = datetime(2026, 9, 10, 9, tzinfo=UTC)
    mappings = FakeMappingRepository(
        {
            "rec-default": _state(now - timedelta(minutes=1)),
            "rec-shop": _state(now - timedelta(minutes=1), business_note="Updated"),
        }
    )
    applications = FakeApplicationRepository(["applied", "unchanged"])
    service = SampleFeishuReversePollService(
        applications,
        mappings,
        (
            FakeClient((_record("rec-default", now),)),
            FakeClient((_record("rec-shop", now),)),
        ),
    )

    result = await service.poll()

    assert result.applied_count == 1
    assert result.unchanged_count == 1
    assert [call["record_id"] for call in applications.calls] == ["rec-default"]


@pytest.mark.asyncio
async def test_reverse_poll_rejects_record_identity_shared_by_tables() -> None:
    now = datetime(2026, 9, 10, 9, tzinfo=UTC)
    record = _record("rec-duplicate", now)
    service = SampleFeishuReversePollService(
        FakeApplicationRepository(),
        FakeMappingRepository({"rec-duplicate": _state(None)}),
        (FakeClient((record,)), FakeClient((record,))),
    )

    with pytest.raises(FeishuSampleReversePollError, match="duplicated across tables"):
        await service.poll()


@pytest.mark.asyncio
async def test_reverse_poll_applies_cleared_business_fields() -> None:
    now = datetime(2026, 9, 10, 9, tzinfo=UTC)
    mappings = FakeMappingRepository(
        {
            "rec-cleared": _state(
                now - timedelta(minutes=1),
                assigned_bd_name="BD A",
                business_note="Old",
            )
        }
    )
    applications = FakeApplicationRepository()
    service = SampleFeishuReversePollService(
        applications,
        mappings,
        (FakeClient((_record("rec-cleared", now, {"分配BD": "BD A"}),)),),
    )

    result = await service.poll()

    assert result.applied_count == 1
    assert applications.calls[0]["fields"] == {"备注": None}
    assert applications.calls[0]["assignment_recipient_open_id"] is None


@pytest.mark.asyncio
async def test_reverse_poll_does_not_clear_existing_assignment_from_blank_cell() -> None:
    now = datetime(2026, 9, 10, 9, tzinfo=UTC)
    applications = FakeApplicationRepository()
    service = SampleFeishuReversePollService(
        applications,
        FakeMappingRepository(
            {
                "rec-1": _state(
                    now - timedelta(minutes=1), assigned_bd_name="BD A"
                )
            }
        ),
        (FakeClient((_record("rec-1", now, {"分配BD": None}),)),),
    )

    result = await service.poll()

    assert result.unchanged_count == 1
    assert applications.calls == []


@pytest.mark.asyncio
async def test_reverse_poll_resolves_text_bd_from_roster() -> None:
    now = datetime(2026, 9, 10, 9, tzinfo=UTC)
    applications = FakeApplicationRepository()
    service = SampleFeishuReversePollService(
        applications,
        FakeMappingRepository({"rec-1": _state(now - timedelta(minutes=1))}),
        (FakeClient((_record("rec-1", now, {"分配BD": "BD B"}),)),),
        recipient_provider=FakeRecipientProvider(),
    )

    result = await service.poll()

    assert result.applied_count == 1
    assert applications.calls[0]["fields"] == {"分配BD": "BD B"}
    assert applications.calls[0]["assignment_recipient_open_id"] == "ou-bd"
