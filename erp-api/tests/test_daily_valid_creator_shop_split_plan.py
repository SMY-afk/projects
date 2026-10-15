from copy import deepcopy

import pytest

from scripts.daily_valid_creator_shop_split_plan import split_plan, verify_split


def sources():
    return {("abc", shop): {"账号名称": "abc",
        "匹配店铺": shop, "业绩": value, "视频数": 1, "直播数": 0,
        "最近有效日期": None, "保留原因": "有业绩；有视频产出"}
        for shop, value in (("跨境3", 100), ("跨境7", 200))}


def baseline():
    return [{"record_id": "original", "fields": {"产品线": "童车", "账号名称": "abc",
        "匹配店铺": "跨境3；跨境7", "业绩": 300, "BD负责人": "BD",
        "数据质量备注": "keep", "最新更新时间": 10}},
        {"record_id": "untouched", "fields": {"产品线": "遥控车", "账号名称": "other",
        "匹配店铺": "", "最新更新时间": 10}}]


def test_bounded_split_preserves_ids_and_does_not_copy_aggregate():
    plan = split_plan(baseline(), sources(), 1)
    assert (plan["updated"], plan["created"], plan["final_count"]) == (1, 1, 3)
    assert plan["operations"]["delete"] == []
    assert [row["fields"]["业绩"] for row in (plan["projected"][0], plan["projected"][2])] == [100, 200]
    assert plan["projected"][2]["fields"]["BD负责人"] == "BD"
    assert plan["projected"][1] == baseline()[1]


def test_missing_shop_evidence_blocks_entire_split():
    evidence = sources()
    evidence.pop(("abc", "跨境7"))
    with pytest.raises(ValueError, match="no complete current source"):
        split_plan(baseline(), evidence, 1)


def test_changed_approved_scope_is_rejected():
    with pytest.raises(ValueError, match="approved scope"):
        split_plan(baseline(), sources())


def test_duplicate_shop_after_split_is_rejected():
    rows = baseline()
    rows.append({"record_id": "duplicate", "fields": sources()[("abc", "跨境7")]})
    with pytest.raises(ValueError, match="duplicate an existing"):
        split_plan(rows, sources(), 1)


def test_readback_catches_unrelated_changes_and_aggregated_metrics():
    plan = split_plan(baseline(), sources(), 1)
    after = deepcopy(plan["projected"])
    for row in after:
        if row["record_id"] != "untouched":
            row["fields"]["最新更新时间"] = 20
    verify_split(baseline(), after, plan, 20)
    after[1]["fields"]["最新更新时间"] = 20
    with pytest.raises(RuntimeError, match="unrelated"):
        verify_split(baseline(), after, plan, 20)
    after[1]["fields"]["最新更新时间"] = 10
    after[2]["fields"]["业绩"] = 300
    with pytest.raises(RuntimeError, match="per-shop field"):
        verify_split(baseline(), after, plan, 20)
