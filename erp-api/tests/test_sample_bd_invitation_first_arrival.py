from datetime import UTC, datetime, timedelta

import pytest

from erp_api.services.feishu_sample_record_snapshot import (
    FeishuListedRecord,
    FeishuRecordSnapshot,
)
from erp_api.services.sample_bd_invitation_ai_priority import AiInvitationSnapshot
from erp_api.services.sample_bd_invitation_protection import (
    BdInvitationLookupSource,
    SampleBdInvitationProtectionService,
)


class _Records:
    def __init__(self, remark=None, *, created_at=None):
        self.fields = {"达人ID": "askform0", "BD负责人": "Alice"}
        if remark is not None:
            self.fields["备注"] = remark
        self.created_at = created_at
        self.updates = []
        self.deleted = []

    async def list_record_snapshots(self, **kwargs):
        return (
            FeishuListedRecord(
                "rec-askform0",
                FeishuRecordSnapshot(self.fields, created_at=self.created_at),
            ),
        )

    async def batch_update_remarks(self, rows):
        self.updates.extend(rows)
        self.fields["备注"] = rows[0][1]
        return ("rec-askform0",)

    async def batch_delete_records(self, ids):
        self.deleted.extend(ids)
        return tuple(ids)


class _Lookup:
    def __init__(self, *, hit):
        self.hit = hit

    async def match_creator_ids(self, creator_ids, *, field_name):
        return frozenset({"askform0"}) if self.hit else frozenset()

    async def list_creator_ids(self):
        return frozenset({"askform0"}) if self.hit else frozenset()

    async def list_invitation_rows(self):
        return (("askform0", "2026/09/22 10:00"),) if self.hit else ()


class _SnapshotStore:
    def __init__(self, snapshot=None):
        self.snapshot = snapshot
        self.saved = []

    async def load(self):
        return self.snapshot

    async def save(self, snapshot):
        self.saved.append(snapshot)
        self.snapshot = snapshot


def _service(records, *, ai_hit, valid_hit=False, now, snapshot_store=None):
    return SampleBdInvitationProtectionService(
        records,
        lookup_sources=(
            BdInvitationLookupSource(
                "（每日更新）有效达人", _Lookup(hit=valid_hit), "达人ID"
            ),
            BdInvitationLookupSource("AI邀约表", _Lookup(hit=ai_hit), "达人ID"),
        ),
        ai_snapshot_store=snapshot_store,
        clock=lambda: now,
    )


@pytest.mark.asyncio
async def test_existing_bd_protection_survives_later_ai_hit() -> None:
    now = datetime(2026, 9, 24, 10, tzinfo=UTC)
    records = _Records(
        "未命中：（每日更新）有效达人、AI邀约表；保护原BD归属；按创建时间保存7天",
        created_at=now - timedelta(hours=25),
    )

    result = await _service(records, ai_hit=True, now=now).refresh()

    assert result.deleted_count == 0
    assert result.active["askform0"].bd_name == "Alice"
    assert result.active["askform0"].expires_at == records.created_at + timedelta(
        days=7
    )
    assert "后续命中AI邀约表不影响原BD保护" in records.fields["备注"]


@pytest.mark.asyncio
async def test_new_unmatched_bd_row_remembers_first_arrival() -> None:
    now = datetime(2026, 9, 24, 10, tzinfo=UTC)
    records = _Records(created_at=now - timedelta(minutes=1))

    first = await _service(records, ai_hit=False, now=now).refresh()
    second = await _service(records, ai_hit=True, now=now).refresh()

    assert "askform0" in first.active
    assert "BD先提交" in records.fields["备注"]
    assert "askform0" in second.active


@pytest.mark.asyncio
async def test_ai_hit_on_first_check_still_uses_24_hour_rule() -> None:
    now = datetime(2026, 9, 24, 10, tzinfo=UTC)
    records = _Records(created_at=now - timedelta(hours=23))

    result = await _service(records, ai_hit=True, now=now).refresh()

    assert result.active == {}
    assert "按创建时间保存24小时" in records.fields["备注"]
    assert "BD先提交" not in records.fields["备注"]


@pytest.mark.asyncio
async def test_both_new_in_same_check_interval_prioritizes_bd() -> None:
    now = datetime(2026, 9, 24, 10, tzinfo=UTC)
    store = _SnapshotStore(
        AiInvitationSnapshot(now - timedelta(minutes=1), frozenset())
    )
    records = _Records(created_at=now - timedelta(seconds=30))

    first = await _service(records, ai_hit=True, now=now, snapshot_store=store).refresh(
        save_ai_snapshot=True
    )
    second = await _service(
        records, ai_hit=True, now=now, snapshot_store=store
    ).refresh()

    assert first.active["askform0"].expires_at == records.created_at + timedelta(days=7)
    assert "同轮新增，BD优先" in records.fields["备注"]
    assert "askform0" in second.active
    assert store.snapshot.creator_ids == frozenset({"askform0"})


@pytest.mark.asyncio
async def test_ai_already_in_previous_snapshot_keeps_24_hour_rule() -> None:
    now = datetime(2026, 9, 24, 10, tzinfo=UTC)
    store = _SnapshotStore(
        AiInvitationSnapshot(now - timedelta(minutes=1), frozenset({"askform0"}))
    )
    records = _Records(created_at=now - timedelta(seconds=30))

    result = await _service(
        records, ai_hit=True, now=now, snapshot_store=store
    ).refresh()

    assert result.active == {}
    assert "按创建时间保存24小时" in records.fields["备注"]


@pytest.mark.asyncio
async def test_missing_or_stale_ai_snapshot_does_not_guess_simultaneity() -> None:
    now = datetime(2026, 9, 24, 10, tzinfo=UTC)
    for previous in (
        None,
        AiInvitationSnapshot(now - timedelta(minutes=3), frozenset()),
    ):
        store = _SnapshotStore(previous)
        records = _Records(created_at=now - timedelta(seconds=30))

        result = await _service(
            records, ai_hit=True, now=now, snapshot_store=store
        ).refresh(save_ai_snapshot=True)

        assert result.active == {}
        assert store.snapshot.creator_ids == frozenset({"askform0"})


@pytest.mark.asyncio
async def test_valid_creator_hit_overrides_same_interval_bd_priority() -> None:
    now = datetime(2026, 9, 24, 10, tzinfo=UTC)
    store = _SnapshotStore(
        AiInvitationSnapshot(now - timedelta(minutes=1), frozenset())
    )
    records = _Records(created_at=now - timedelta(seconds=30))

    result = await _service(
        records, ai_hit=True, valid_hit=True, now=now, snapshot_store=store
    ).refresh()

    assert result.active == {}
    assert "已有BD合作，不重新自动分配" in records.fields["备注"]


@pytest.mark.asyncio
async def test_precheck_reads_ai_snapshot_without_advancing_it() -> None:
    now = datetime(2026, 9, 24, 10, tzinfo=UTC)
    previous = AiInvitationSnapshot(now - timedelta(minutes=1), frozenset())
    store = _SnapshotStore(previous)
    records = _Records(created_at=now - timedelta(seconds=30))

    result = await _service(
        records, ai_hit=True, now=now, snapshot_store=store
    ).refresh()

    assert "askform0" in result.active
    assert store.snapshot is previous
    assert store.saved == []


@pytest.mark.asyncio
async def test_valid_creator_hit_still_overrides_earlier_bd_protection() -> None:
    now = datetime(2026, 9, 24, 10, tzinfo=UTC)
    records = _Records(
        "未命中：（每日更新）有效达人、AI邀约表；保护原BD归属；按创建时间保存7天",
        created_at=now - timedelta(hours=23),
    )

    result = await _service(records, ai_hit=True, valid_hit=True, now=now).refresh()

    assert result.active == {}
    assert "已有BD合作，不重新自动分配" in records.fields["备注"]
    assert "按创建时间保存24小时" in records.fields["备注"]
