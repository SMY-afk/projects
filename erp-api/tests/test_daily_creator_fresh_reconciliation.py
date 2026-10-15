"""A full refresh corrects retained history without deleting or guessing."""

from copy import deepcopy
from datetime import date

import pytest

from scripts.daily_valid_creator_core import date_millis
from scripts.daily_valid_creator_fresh_reconciliation import (
    fresh_reconciliation_preview,
    verify_fresh_projection,
)


def source(account="creator", shop="跨境3", owner="BD-new", day=None):
    return {(account, shop): {"account": account, "bd": owner,
            "sample_day": day or date(2026, 10, 10), "conflict": False}}


def active(account="creator", shop="跨境3", owner="BD-new"):
    return {(account, shop): {"账号名称": account, "BD负责人": owner,
            "匹配店铺": shop, "同意样品日期": date_millis(date(2026, 10, 10)),
            "最近有效日期": date_millis(date(2026, 10, 12)), "业绩": 100,
            "视频数": 2, "直播数": 0, "保留原因": "有业绩；有视频产出",
            "数据质量备注": ""}}


def row(record_id="old", **overrides):
    return {"record_id": record_id, "fields": {"账号名称": "creator",
            "匹配店铺": "跨境7", "BD负责人": "BD-old",
            "同意样品日期": date_millis(date(2026, 1, 1)), "业绩": 999,
            "视频数": 99, "直播数": 9, "保留原因": "有业绩",
            "最新更新时间": 123, **overrides}}


def applied(current, plan):
    result = deepcopy(current)
    by_id = {item["record_id"]: item for item in result}
    for record_id, changes in plan["operations"]["update"]:
        by_id[record_id]["fields"].update(changes)
    for ordinal, fields in enumerate(plan["operations"]["create"]):
        result.append({"record_id": f"created-{ordinal}", "fields": fields})
    return result


def assert_stable(desired, current, base, excluded=()):
    before = deepcopy(current)
    plan = fresh_reconciliation_preview(desired, current, base,
                                        excluded_accounts=excluded)
    assert current == before
    assert plan["operations"]["delete"] == []
    after = applied(current, plan)
    verify_fresh_projection(desired, current, after, base, excluded_accounts=excluded)
    second = fresh_reconciliation_preview(desired, after, base,
                                          excluded_accounts=excluded)
    assert (second["updates"], second["creates"], second["deduplicates"]) == (0, 0, 0)
    return plan, after


def test_wrong_shop_owner_and_date_are_corrected_reusing_same_id():
    plan, after = assert_stable(active(), [row()], source())
    assert plan["creates"] == 0
    assert after[0]["record_id"] == "old"
    assert after[0]["fields"]["匹配店铺"] == "跨境3"
    assert after[0]["fields"]["BD负责人"] == "BD-new"
    assert after[0]["fields"]["业绩"] == 100


def test_inactive_but_declared_history_is_corrected_and_marked_not_current():
    plan, after = assert_stable({}, [row()], source())
    fields = after[0]["fields"]
    assert fields["匹配店铺"] == "跨境3"
    assert fields["BD负责人"] == "BD-new"
    assert fields["同意样品日期"] == date_millis(date(2026, 10, 10))
    assert fields["保留原因"].startswith("历史留存")
    assert fields["业绩"] == fields["视频数"] == fields["直播数"] == 0
    assert plan["creates"] == 0


def test_duplicates_are_preserved_corrected_but_only_one_is_current():
    current = [row("first", 匹配店铺="跨境3"), row("second", 匹配店铺="跨境3")]
    plan, after = assert_stable(active(), current, source())
    assert {item["record_id"] for item in after} == {"first", "second"}
    assert all(item["fields"]["BD负责人"] == "BD-new" for item in after)
    assert sum(not item["fields"]["保留原因"].startswith("历史留存") for item in after) == 1
    assert sum(item["fields"]["业绩"] for item in after) == 100
    assert plan["history_duplicate_rows"] == 1


def test_wrong_shop_with_two_distinct_owners_cannot_be_guessed():
    base = source(owner="BD-3") | source(shop="跨境7", owner="BD-7")
    desired = active(owner="BD-3") | active(shop="跨境7", owner="BD-7")
    plan, after = assert_stable(desired, [row(匹配店铺="跨境4")], base)
    original = next(item for item in after if item["record_id"] == "old")["fields"]
    assert original["BD负责人"] == "BD-old"
    assert original["匹配店铺"] == "跨境4"
    assert original["保留原因"].startswith("待核验")
    assert plan["creates"] == 2


def test_matching_provenance_migrates_only_to_that_shop():
    base = source(owner="BD-3") | source(shop="跨境7", owner="BD-7")
    desired = active(owner="BD-3") | active(shop="跨境7", owner="BD-7")
    current = [row(匹配店铺="", BD负责人="BD-7",
                   同意样品日期=date_millis(date(2026, 10, 10)))]
    plan, after = assert_stable(desired, current, base)
    assert after[0]["fields"]["BD负责人"] == "BD-7"
    assert after[0]["fields"]["匹配店铺"] == "跨境7"
    assert plan["creates"] == 1


def test_source_missing_history_is_preserved_but_not_effective():
    current = [row(账号名称="not-in-source")]
    _, after = assert_stable(active(), current, source())
    assert after[0]["fields"]["BD负责人"] == "BD-old"
    assert after[0]["fields"]["保留原因"].startswith("待核验")


def test_local_alias_is_corrected_to_display_suffix():
    desired = active(shop="本土店")
    desired[("creator", "本土店")]["匹配店铺"] = "本土2店"
    _, after = assert_stable(desired, [row(匹配店铺="本土店")], source(shop="本土店"))
    assert after[0]["fields"]["匹配店铺"] == "本土2店"


def test_unverified_historical_local_alias_is_also_renamed():
    current = [row(账号名称="missing", 匹配店铺="本土店")]
    _, after = assert_stable(active(), current, source())
    assert after[0]["fields"]["匹配店铺"] == "本土2店"
    assert after[0]["fields"]["保留原因"].startswith("待核验")


def test_two_shop_history_with_same_owner_and_date_is_ambiguous():
    base = source(owner="BD-same") | source(shop="跨境7", owner="BD-same")
    desired = active(owner="BD-same") | active(shop="跨境7", owner="BD-same")
    current = [row(匹配店铺="", BD负责人="BD-same",
                   同意样品日期=date_millis(date(2026, 10, 10)))]
    plan, after = assert_stable(desired, current, base)
    assert plan["creates"] == 2
    assert after[0]["fields"]["匹配店铺"] == ""
    assert after[0]["fields"]["保留原因"].startswith("待核验")


def test_known_shop_owner_is_corrected_without_moving_to_other_owner_shop():
    base = source(owner="BD-3") | source(shop="跨境7", owner="BD-7")
    desired = active(owner="BD-3") | active(shop="跨境7", owner="BD-7")
    current = [row(匹配店铺="跨境3", BD负责人="BD-7",
                   同意样品日期=date_millis(date(2026, 10, 10)))]
    plan, after = assert_stable(desired, current, base)
    assert plan["creates"] == 1
    assert after[0]["fields"]["匹配店铺"] == "跨境3"
    assert after[0]["fields"]["BD负责人"] == "BD-3"


def test_yana_all_rows_are_exactly_protected_and_no_new_row_created():
    current = [row("yana-first", 账号名称=" @YANA_OK1 ", 匹配店铺="跨境7"),
               row("yana-second", 账号名称="yana_ok1", 匹配店铺="")]
    base = source("yana_ok1") | source()
    desired = active("yana_ok1") | active()
    plan, after = assert_stable(desired, current, base, excluded=("yana_ok1",))
    assert after[:2] == current
    assert plan["protected_record_ids"] == ["yana-first", "yana-second"]
    assert all(fields["账号名称"] != "yana_ok1" for fields in plan["operations"]["create"])


def test_verify_rejects_protected_timestamp_or_missing_historical_id():
    current = [row("yana", 账号名称="yana_ok1")]
    after = deepcopy(current)
    after[0]["fields"]["最新更新时间"] = 999
    with pytest.raises(RuntimeError, match="Protected"):
        verify_fresh_projection({}, current, after, {}, excluded_accounts=("yana_ok1",))
    with pytest.raises(RuntimeError, match="Historical record IDs"):
        verify_fresh_projection({}, current, [], {}, excluded_accounts=("yana_ok1",))


def test_conflicting_source_and_desired_identity_is_rejected():
    with pytest.raises(ValueError, match="master"):
        fresh_reconciliation_preview(active(shop="跨境7"), [], source())


def test_duplicate_target_ids_are_rejected_before_any_plan():
    with pytest.raises(ValueError, match="record IDs"):
        fresh_reconciliation_preview(active(), [row(), row()], source())
