from types import SimpleNamespace

import pytest

from erp_api.services.feishu_table_mirror_client import FeishuMirrorRecord
from erp_api.services.sample_ai_invitation_mirror import (
    AI_INVITATION_CREATOR_FIELD,
    AI_INVITATION_SOURCE_RECORD_FIELD,
    AI_INVITATION_TIME_FIELD,
    SampleAiInvitationMirrorService,
)
from erp_api.workers.sample_feishu_maintenance_jobs import sync_ai_invitation_mirror_job


class _Client:
    def __init__(self, records=(), fields=None) -> None:
        self.records = tuple(records)
        self.fields = fields or {}
        self.created = []
        self.updated = []
        self.deleted = []

    async def list_field_metadata(self):
        return self.fields

    async def list_records(self, *, field_names):
        return self.records

    async def batch_create(self, rows):
        self.created.append(tuple(rows))
        return len(rows)

    async def batch_update(self, rows):
        self.updated.append(tuple(rows))
        return len(rows)

    async def batch_delete(self, rows):
        self.deleted.append(tuple(rows))
        return len(rows)


def _record(record_id, creator_id, invitation_time, source_id=None):
    fields = {
        AI_INVITATION_CREATOR_FIELD: creator_id,
        AI_INVITATION_TIME_FIELD: invitation_time,
    }
    if source_id is not None:
        fields[AI_INVITATION_SOURCE_RECORD_FIELD] = source_id
    return FeishuMirrorRecord(record_id, fields)


@pytest.mark.asyncio
async def test_sync_creates_updates_and_deletes_only_managed_rows() -> None:
    source = _Client(
        (
            _record("src-new", "Creator-New", 1_700_000_000_000),
            _record("src-changed", "Creator-Changed", 1_800_000_000_000),
        )
    )
    target = _Client(
        (
            _record("dst-changed", "Old", 1_700_000_000_000, "src-changed"),
            _record("dst-stale", "Stale", 1_600_000_000_000, "src-stale"),
            _record("dst-manual", "Manual", None),
        )
    )

    result = await SampleAiInvitationMirrorService(source, target).sync()

    assert (result.created_count, result.updated_count, result.deleted_count) == (
        1,
        1,
        1,
    )
    assert target.created == [
        (
            {
                AI_INVITATION_CREATOR_FIELD: "Creator-New",
                AI_INVITATION_TIME_FIELD: 1_700_000_000_000,
                AI_INVITATION_SOURCE_RECORD_FIELD: "src-new",
            },
        )
    ]
    assert target.updated[0][0][0] == "dst-changed"
    assert target.deleted == [("dst-stale",)]


@pytest.mark.asyncio
async def test_second_preview_is_zero_difference() -> None:
    source = _Client((_record("src-1", "Creator", 1_700_000_000_000),))
    target = _Client((_record("dst-1", "Creator", 1_700_000_000_000, "src-1"),))

    result = await SampleAiInvitationMirrorService(source, target).sync(dry_run=True)

    assert (result.created_count, result.updated_count, result.deleted_count) == (
        0,
        0,
        0,
    )
    assert target.created == []
    assert target.updated == []
    assert target.deleted == []


@pytest.mark.asyncio
async def test_validate_requires_exact_source_and_target_field_types() -> None:
    source = _Client(
        fields={
            AI_INVITATION_CREATOR_FIELD: SimpleNamespace(field_type=1),
            AI_INVITATION_TIME_FIELD: SimpleNamespace(field_type=5),
        }
    )
    target = _Client(
        fields={
            AI_INVITATION_CREATOR_FIELD: SimpleNamespace(field_type=1),
            AI_INVITATION_TIME_FIELD: SimpleNamespace(field_type=5),
            AI_INVITATION_SOURCE_RECORD_FIELD: SimpleNamespace(field_type=1),
        }
    )

    await SampleAiInvitationMirrorService(source, target).validate()

    target.fields[AI_INVITATION_TIME_FIELD] = SimpleNamespace(field_type=1)
    with pytest.raises(RuntimeError, match="target fields"):
        await SampleAiInvitationMirrorService(source, target).validate()


@pytest.mark.asyncio
async def test_worker_job_returns_mirror_counts() -> None:
    result = SimpleNamespace(
        source_count=12,
        target_count=10,
        created_count=2,
        updated_count=1,
        deleted_count=0,
    )

    class _Service:
        async def sync(self):
            return result

    assert (
        await sync_ai_invitation_mirror_job(
            {"sample_ai_invitation_mirror_service": _Service()}
        )
        == result.__dict__
    )
