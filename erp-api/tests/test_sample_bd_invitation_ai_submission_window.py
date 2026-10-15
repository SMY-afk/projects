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


class Records:
    def __init__(self, submitted, remark=""):
        self.created_at = submitted
        self.fields = {"达人ID": "erika.withak", "BD负责人": "Alice", "备注": remark}
        self.deleted = []

    async def list_record_snapshots(self, **kwargs):
        return (
            FeishuListedRecord(
                "record-erika",
                FeishuRecordSnapshot(self.fields, created_at=self.created_at),
            ),
        )

    async def batch_update_remarks(self, rows):
        self.fields["备注"] = rows[0][1]

    async def batch_delete_records(self, ids):
        self.deleted.extend(ids)


class AI:
    def __init__(self, rows):
        self.rows = rows
        self.reads = 0

    async def list_invitation_rows(self):
        self.reads += 1
        return self.rows

    async def match_creator_ids(self, *args, **kwargs):
        raise AssertionError("Membership cannot bypass submission time verification")

    async def list_creator_ids(self):
        raise AssertionError("AI source must not be read a second time")


class Valid:
    async def match_creator_ids(self, *args, **kwargs):
        return frozenset({"erika.withak"})


class Store:
    def __init__(self, previous):
        self.previous = previous
        self.saved = []

    async def load(self):
        return self.previous

    async def save(self, snapshot):
        self.saved.append(snapshot)


async def refresh(records, ai, now, *, store=None, valid=False):
    sources = [BdInvitationLookupSource("AI邀约表", ai, "达人ID")]
    if valid:
        sources.append(
            BdInvitationLookupSource("（每日更新）有效达人", Valid(), "账号名称")
        )
    return await SampleBdInvitationProtectionService(
        records,
        lookup_sources=tuple(sources),
        ai_snapshot_store=store,
        clock=lambda: now,
    ).refresh(save_ai_snapshot=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("snapshot_present", [False, True])
async def test_erika_expired_time_is_unmatched_even_when_snapshot_contains_id(
    snapshot_present,
):
    now = datetime(2026, 10, 14, 9, tzinfo=UTC)
    records = Records(
        now - timedelta(minutes=5), "命中：AI邀约表；按创建时间保存24小时"
    )
    ai = AI((("erika.withak", "2026/09/20 11:32"),))
    store = (
        Store(
            AiInvitationSnapshot(
                now - timedelta(seconds=60), frozenset({"erika.withak"})
            )
        )
        if snapshot_present
        else None
    )
    result = await refresh(records, ai, now, store=store)
    assert result.active["erika.withak"].expires_at == records.created_at + timedelta(
        days=7
    )
    assert records.fields["备注"].startswith("未命中：AI邀约表")
    assert ai.reads == 1
    assert records.deleted == []


@pytest.mark.asyncio
async def test_hit_is_at_submission_not_refreshed_now():
    submitted = datetime(2026, 9, 27, 3, 31, tzinfo=UTC)
    records = Records(submitted)
    result = await refresh(
        records,
        AI((("erika.withak", "2026/09/20 11:32"),)),
        submitted + timedelta(hours=1),
    )
    assert result.active == {}
    assert records.fields["备注"].startswith("命中：AI邀约表")


@pytest.mark.asyncio
async def test_old_ai_time_does_not_remove_independent_valid_creator_hit():
    now = datetime(2026, 10, 14, 9, tzinfo=UTC)
    records = Records(now - timedelta(minutes=1))
    result = await refresh(
        records, AI((("erika.withak", "2026/09/20 11:32"),)), now, valid=True
    )
    assert result.active == {}
    assert "命中：（每日更新）有效达人" in records.fields["备注"]
    assert "命中：AI邀约表" not in records.fields["备注"]


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", [None, "invalid", "2027/01/01"])
async def test_bad_time_is_pending_without_protection_or_expired_deletion(raw):
    now = datetime(2026, 10, 14, 9, tzinfo=UTC)
    records = Records(now - timedelta(days=8))
    result = await refresh(records, AI((("erika.withak", raw),)), now)
    assert result.active == {}
    assert records.deleted == []
    assert "待核验" in records.fields["备注"]
    assert "未命中" not in records.fields["备注"]


@pytest.mark.asyncio
async def test_pending_time_retains_prior_bd_priority_marker_for_recovery():
    now = datetime(2026, 10, 14, 9, tzinfo=UTC)
    records = Records(
        now - timedelta(hours=25), "未命中：AI邀约表；保护原BD归属；按创建时间保存7天"
    )
    result = await refresh(records, AI((("erika.withak", None),)), now)
    assert result.active == {}
    assert "原保护凭证保留" in records.fields["备注"]
    recovered = await refresh(records, AI((("erika.withak", "2026/10/12"),)), now)
    assert "erika.withak" in recovered.active
    assert "后续命中AI邀约表不影响原BD保护" in records.fields["备注"]


@pytest.mark.asyncio
async def test_pending_ai_time_preserves_independent_daily_hit():
    now = datetime(2026, 10, 14, 9, tzinfo=UTC)
    records = Records(now - timedelta(minutes=1))
    result = await refresh(records, AI((("erika.withak", None),)), now, valid=True)
    assert result.active == {}
    assert "命中：（每日更新）有效达人" in records.fields["备注"]
    assert "待核验" in records.fields["备注"]
