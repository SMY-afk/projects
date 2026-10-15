"""One-off history deletion requires current sources, unique keys and exact tags."""

from copy import deepcopy
from datetime import date

import pytest

from scripts.daily_valid_creator_cleanup_plan import cleanup_preview, verify_cleanup
from scripts.daily_valid_creator_core import date_millis
from scripts.daily_valid_creator_history_identity import (
    DUPLICATE_REASON,
    HISTORY_REASON,
    PENDING_REASON,
)


def master(account="creator", shop="跨境3", owner="BD"):
    return {(account, shop): {"account": account, "bd": owner,
            "sample_day": date(2026, 1, 1), "conflict": False}}


def target(record_id="history", account="creator", shop="跨境3", reason=HISTORY_REASON,
           owner="BD"):
    return {"record_id": record_id, "fields": {"账号名称": account,
            "匹配店铺": shop, "BD负责人": owner,
            "同意样品日期": date_millis(date(2026, 1, 1)),
            "最近有效日期": None, "业绩": 0, "视频数": 0, "直播数": 0,
            "保留原因": reason, "数据质量备注": "old-note", "最新更新时间": 123}}


def active(account="creator", shop="跨境3", owner="BD"):
    return {(account, shop): {"账号名称": account, "匹配店铺": shop,
            "BD负责人": owner, "同意样品日期": date_millis(date(2026, 1, 1)),
            "最近有效日期": date_millis(date(2026, 10, 13)), "业绩": 100,
            "视频数": 1, "直播数": 0, "保留原因": "有业绩；有视频产出",
            "数据质量备注": ""}}


def test_exact_inactive_history_with_unique_declared_master_is_eligible():
    rows = [target()]
    before = deepcopy(rows)
    plan = cleanup_preview(rows, {}, master())
    assert rows == before
    assert plan["delete_ids"] == ["history"]
    assert plan["counts"]["delete"] == 1
    assert plan["skip_reasons"] == {}
    verify_cleanup(rows, [], plan["delete_ids"])


def test_old_history_that_is_currently_active_must_not_be_deleted():
    plan = cleanup_preview([target()], active(), master())
    assert plan["delete_ids"] == []
    assert plan["skip_reasons"]["history"] == "current_effective_projection"


@pytest.mark.parametrize("tag", [HISTORY_REASON + " ", "历史留存", PENDING_REASON,
                                 DUPLICATE_REASON, "有视频产出", ""])
def test_only_the_exact_authorized_tag_is_eligible(tag):
    plan = cleanup_preview([target(reason=tag)], {}, master())
    assert plan["delete_ids"] == []
    assert "history" in plan["skip_reasons"]


def test_missing_master_source_does_not_prove_history_invalid():
    plan = cleanup_preview([target()], {}, master(account="other"))
    assert plan["delete_ids"] == []
    assert plan["skip_reasons"]["history"] == "projected_pending_or_nonhistory"


def test_unscoped_master_shop_cannot_authorize_a_delete():
    plan = cleanup_preview([target(shop="")], {}, master(shop=""))
    assert plan["delete_ids"] == []
    assert plan["skip_reasons"]["history"] == "source_shop_unverified"


def test_duplicate_original_keys_are_preserved_even_with_distinct_mapped_shops():
    rows = [target("first", shop="", owner="BD-3"),
            target("second", shop="", owner="BD-7")]
    base = master(owner="BD-3") | master(shop="跨境7", owner="BD-7")
    plan = cleanup_preview(rows, {}, base)
    assert plan["delete_ids"] == []
    assert set(plan["skip_reasons"].values()) == {"duplicate_original_key"}


def test_duplicate_mapped_keys_are_preserved_even_with_distinct_original_shops():
    rows = [target("first", shop="跨境7"), target("second", shop="跨境4")]
    plan = cleanup_preview(rows, {}, master())
    assert plan["delete_ids"] == []
    assert set(plan["skip_reasons"].values()) == {"duplicate_mapped_key"}


def test_local_aliases_count_as_the_same_original_business_key():
    rows = [target("first", shop="本土店"), target("second", shop="本土2店")]
    plan = cleanup_preview(rows, {}, master(shop="本土店"))
    assert plan["delete_ids"] == []
    assert set(plan["skip_reasons"].values()) == {"duplicate_original_key"}


def test_yana_pending_and_duplicate_history_all_remain_exactly_unchanged():
    rows = [target("yana-1", account=" @YANA_OK1 "),
            target("yana-2", account="yana_ok1", shop="跨境7"),
            target("pending", account="pending", reason=PENDING_REASON),
            target("duplicate", account="duplicate", reason=DUPLICATE_REASON), target()]
    base = master("yana_ok1") | master("pending") | master("duplicate") | master()
    plan = cleanup_preview(rows, {}, base)
    assert plan["delete_ids"] == ["history"]
    after = deepcopy(rows[:-1])
    verify_cleanup(rows, after, plan["delete_ids"])
    assert after == rows[:-1]
    assert plan["skip_reasons"]["yana-1"] == plan["skip_reasons"]["yana-2"] == "excluded_account"


def test_preview_never_mutates_current_desired_or_master_and_hash_binds_full_fields():
    rows, desired, base = [target()], {}, master()
    before = deepcopy((rows, desired, base))
    first = cleanup_preview(rows, desired, base)
    assert (rows, desired, base) == before
    rows[0]["fields"]["数据质量备注"] = "changed-by-human"
    second = cleanup_preview(rows, desired, base)
    assert first["delete_ids"] == second["delete_ids"]
    assert first["hash"] != second["hash"]


def test_hash_is_stable_across_row_and_source_dictionary_order():
    rows = [target("one", account="one"), target("two", account="two")]
    base = master("one") | master("two")
    first = cleanup_preview(rows, {}, base)
    second = cleanup_preview(list(reversed(rows)), {}, dict(reversed(list(base.items()))))
    assert first["hash"] == second["hash"]


@pytest.mark.parametrize("mutation", ["field", "undeclared_delete", "extra_id", "kept_delete"])
def test_readback_rejects_any_change_outside_exact_authorized_deletes(mutation):
    before = [target("delete"), target("keep", account="keep")]
    after = deepcopy(before[1:])
    if mutation == "field":
        after[0]["fields"]["最新更新时间"] = 456
    elif mutation == "undeclared_delete":
        after = []
    elif mutation == "extra_id":
        after.append(target("unexpected", account="unexpected"))
    else:
        after = deepcopy(before)
    with pytest.raises(RuntimeError):
        verify_cleanup(before, after, ["delete"])


def test_duplicate_or_unknown_authorized_delete_ids_are_rejected():
    before = [target()]
    for ids in (["history", "history"], ["unknown"]):
        with pytest.raises(ValueError, match="delete IDs"):
            verify_cleanup(before, [], ids)
