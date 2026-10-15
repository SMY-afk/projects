from datetime import date
from types import SimpleNamespace
from uuid import uuid4

import pytest

from erp_api.services.feishu_sample_record_snapshot import (
    FeishuListedRecord,
    FeishuRecordSnapshot,
)
from erp_api.services.sample_cooperation_reader import SampleCooperationReader
from erp_api.services.sample_cooperation_rules import (
    COOPERATION_ACTIVE_CREATOR_EVENT,
    COOPERATION_ALLOWED_EVENT,
    COOPERATION_EXCEPTION_EVENT,
    CooperationCandidate,
    decide_cooperation,
)


def record(identifier, fields):
    return FeishuListedRecord(identifier, FeishuRecordSnapshot(fields))


class Client:
    def __init__(self, records=()):
        self.records, self.calls = records, []

    async def list_record_snapshots(self, **kwargs):
        self.calls.append(kwargs)
        return self.records


async def snapshot(*, owner="俊楚", people=True, status="在岗", line="跨境3",
                   extra_daily=(), extra_roster=(), cooperation=()):
    tables = (Client(cooperation), Client())
    daily = Client((record("daily", {"账号名称": "@_brandi_0824",
        "匹配店铺": line, "BD负责人": owner}), *extra_daily))
    roster = Client((record("bd", {"BD姓名": "example-2b3220d55335", "在岗状态": status,
        "飞书人员": [{"id": "ou-junchu"}] if people else []}), *extra_roster))
    reader = SampleCooperationReader(tuple(SimpleNamespace(label=label, client=client,
        view_id=f"view-{index}") for index, (label, client) in
        enumerate(zip(("童车", "遥控车"), tables))), roster, daily)
    return await reader.read(), reader, tables, daily


def decide(value):
    return decide_cooperation(CooperationCandidate(uuid4(), "application", "_brandi_0824",
        "fanfu toy tool"), value, today=date(2026, 10, 12))


@pytest.mark.asyncio
async def test_daily_owner_resolves_current_person_without_skipping_cooperation_tables():
    value, _, tables, daily = await snapshot()
    decision = decide(value)
    assert decision.event_type == COOPERATION_ACTIVE_CREATOR_EVENT
    assert decision.reason == "active_creator_daily_bd_verified"
    assert [(r.name, r.open_id) for r in decision.recipients] == [("example-2b3220d55335", "ou-junchu")]
    assert decision.blocks_assignment
    assert "（每日更新）有效达人" in decision.sources
    assert all(len(client.calls) == 1 for client in tables)
    assert set(daily.calls[0]["field_names"]) == {"账号名称", "BD负责人", "匹配店铺", "保留原因"}


@pytest.mark.asyncio
@pytest.mark.parametrize("kwargs,reason", [
    ({"people": False}, "active_creator_bd_unresolved"),
    ({"owner": ""}, "active_creator_bd_missing"),
    ({"line": ""}, "active_creator_shop_missing"),
])
async def test_daily_owner_incomplete_data_stays_fail_closed(kwargs, reason):
    value, *_ = await snapshot(**kwargs)
    decision = decide(value)
    assert decision.event_type == COOPERATION_EXCEPTION_EVENT
    assert decision.reason == reason
    assert not decision.recipients


@pytest.mark.asyncio
async def test_departed_daily_owner_does_not_protect_a_creator():
    value, *_ = await snapshot(status="离职")
    decision = decide(value)
    assert decision.event_type == COOPERATION_ALLOWED_EVENT
    assert "_brandi_0824" not in value.valid_creator_ids


@pytest.mark.asyncio
async def test_daily_membership_and_owner_are_shop_scoped():
    value, *_ = await snapshot(line="跨境4")
    decision = decide(value)
    assert decision.event_type == COOPERATION_ALLOWED_EVENT
    assert decision.reason == "not_registered"


@pytest.mark.asyncio
async def test_multiple_valid_daily_owners_do_not_notify_both():
    value, *_ = await snapshot(extra_daily=(record("daily-2", {
        "账号名称": "_brandi_0824", "匹配店铺": "跨境3", "BD负责人": "Alice"}),),
        extra_roster=(record("bd-2", {"BD姓名": "Alice", "在岗状态": "在岗",
            "飞书人员": [{"id": "ou-alice"}]}),))
    decision = decide(value)
    assert decision.event_type == COOPERATION_EXCEPTION_EVENT
    assert decision.reason == "active_creator_bd_ambiguous"
    assert not decision.recipients


@pytest.mark.asyncio
async def test_malformed_cooperation_row_is_not_overridden_by_daily_owner():
    value, *_ = await snapshot(cooperation=(record("coop", {
        "帐号名称": "_brandi_0824", "BD负责人": "俊楚", "同意样品日期": "invalid"}),))
    decision = decide(value)
    assert decision.event_type == COOPERATION_EXCEPTION_EVENT
    assert decision.reason == "sample_approved_date_invalid"


@pytest.mark.asyncio
async def test_notification_recipient_is_rechecked_for_current_membership():
    _value, reader, *_ = await snapshot(status="离职")
    from erp_api.services.sample_cooperation_rules import CooperationRecipient
    assert await reader.resolve_current_recipient(CooperationRecipient("example-2b3220d55335", "ou-junchu")) is None


@pytest.mark.asyncio
async def test_daily_owner_conflicting_with_cooperation_owner_blocks_notification():
    value, *_ = await snapshot(cooperation=(record("coop", {
        "帐号名称": "_brandi_0824", "BD负责人": "Alice", "同意样品日期": "2026-10-12"}),),
        extra_roster=(record("bd-2", {"BD姓名": "Alice", "在岗状态": "在岗",
            "飞书人员": [{"id": "ou-alice"}]}),))
    decision = decide(value)
    assert decision.event_type == COOPERATION_EXCEPTION_EVENT
    assert decision.reason == "active_creator_bd_conflict"
    assert not decision.recipients


@pytest.mark.asyncio
async def test_one_person_mapped_to_two_roster_members_is_not_accepted():
    value, *_ = await snapshot(extra_roster=(record("bd-2", {
        "BD姓名": "Alice", "在岗状态": "在岗", "飞书人员": [{"id": "ou-junchu"}]}),))
    decision = decide(value)
    assert decision.event_type == COOPERATION_EXCEPTION_EVENT
    assert decision.reason == "active_creator_bd_unresolved"
