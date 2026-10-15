from types import SimpleNamespace

import pytest

from erp_api.services.feishu_bd_roster_provider import (
    BD_NAME_FIELD,
    BD_PERSON_FIELD,
    BD_STATUS_FIELD,
)
from erp_api.services.feishu_creator_export_service import FEISHU_CREATOR_FIELDS
from erp_api.services.feishu_sample_record_snapshot import (
    FeishuListedRecord,
    FeishuRecordSnapshot,
)
from erp_api.services.sample_cooperation_reader import SampleCooperationReader


class SnapshotClient:
    def __init__(self, records=()):
        self.records = records
        self.calls = []

    async def list_record_snapshots(self, **kwargs):
        self.calls.append(kwargs)
        return self.records


def record(record_id, fields):
    return FeishuListedRecord(record_id, FeishuRecordSnapshot(fields))


def reader_for(daily_records):
    cooperation = tuple(SnapshotClient((record(f"cooperation-{index}", {
        FEISHU_CREATOR_FIELDS[0]: "cooperation-only",
        FEISHU_CREATOR_FIELDS[1]: "Alice",
        FEISHU_CREATOR_FIELDS[2]: "2026-10-13",
    }),)) for index in range(2))
    daily = SnapshotClient(daily_records)
    roster = SnapshotClient((record("member", {
        BD_NAME_FIELD: "Alice", BD_STATUS_FIELD: "在岗",
        BD_PERSON_FIELD: [{"id": "ou-alice", "name": "Alice"}],
    }),))
    reader = SampleCooperationReader(tuple(SimpleNamespace(
        label=f"table-{index}", client=client, view_id=f"view-{index}",
    ) for index, client in enumerate(cooperation)), roster, daily)
    return reader, daily, cooperation


@pytest.mark.asyncio
async def test_reader_requests_retention_reason_without_changing_cooperation_fields():
    reader, daily, cooperation = reader_for(())

    snapshot = await reader.read()

    assert daily.calls[0]["field_names"] == (
        "账号名称", "BD负责人", "匹配店铺", "保留原因",
    )
    assert all(client.calls[0]["field_names"] == FEISHU_CREATOR_FIELDS
               for client in cooperation)
    assert len(snapshot.rows) == 2
    assert snapshot.recipients["alice"].open_id == "ou-alice"
    assert snapshot.current_bd_names == frozenset({"alice"})


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", (
    "历史留存", "历史留存；缺少当前有效证据", " 待核验：匹配店铺 ",
    [{"text": "历史留存；不参与分配"}], [{"text": "待核验"}],
))
async def test_explicit_historical_or_unverified_daily_rows_do_not_protect_creator(reason):
    reader, _, _ = reader_for((record("retained", {
        "账号名称": "@Creator-One", "BD负责人": "Alice", "匹配店铺": "跨境3",
        "保留原因": reason,
    }),))

    snapshot = await reader.read()

    assert snapshot.daily_valid_rows == ()
    assert snapshot.valid_creator_ids == frozenset()
    assert len(snapshot.rows) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", (
    None, "", " ", "有业绩", "有寄样；有视频产出", "人工备注：待核验附件",
))
async def test_blank_or_current_retention_reason_keeps_existing_daily_rules(reason):
    reader, _, _ = reader_for((record("active", {
        "账号名称": " @Creator-One\u200b ", "BD负责人": "Alice",
        "匹配店铺": "跨境3", "保留原因": reason,
    }), record("departed", {
        "账号名称": "Departed-Creator", "BD负责人": "Departed",
        "匹配店铺": "跨境7", "保留原因": reason,
    })))

    snapshot = await reader.read()

    assert tuple(row.record_id for row in snapshot.daily_valid_rows) == (
        "active", "departed",
    )
    assert tuple(row.source for row in snapshot.daily_valid_rows) == ("跨境3", "跨境7")
    assert snapshot.valid_creator_ids == frozenset({"creator-one"})


@pytest.mark.asyncio
async def test_current_creator_row_survives_when_historical_row_has_same_account():
    reader, _, _ = reader_for((record("history", {
        "账号名称": "creator-one", "BD负责人": "Other BD", "匹配店铺": "跨境3",
        "保留原因": "历史留存；旧负责人不参与分配",
    }), record("current", {
        "账号名称": "@Creator-One", "BD负责人": "Alice", "匹配店铺": "跨境3",
        "保留原因": "有业绩",
    })))

    snapshot = await reader.read()

    assert tuple(row.record_id for row in snapshot.daily_valid_rows) == ("current",)
    assert snapshot.valid_creator_ids == frozenset({"creator-one"})
