from scripts.rename_daily_valid_creator_local_shop import plan, renamed_value


def test_renamed_value_changes_only_exact_local_shop_token() -> None:
    assert renamed_value("本土店") == "本土2店"
    assert renamed_value("跨境4；本土店") == "跨境4；本土2店"
    assert renamed_value("本土2店；本土店") == "本土2店"
    assert renamed_value("本土店铺") == "本土店铺"


def test_plan_is_stable_and_zero_after_rename() -> None:
    rows = [
        {"record_id": "rec-b", "fields": {"匹配店铺": "跨境4；本土店"}},
        {"record_id": "rec-a", "fields": {"匹配店铺": "跨境3"}},
    ]
    preview = plan(rows)
    assert preview["count"] == 1
    assert preview["updates"] == [
        {
            "record_id": "rec-b",
            "before": "跨境4；本土店",
            "after": "跨境4；本土2店",
        }
    ]
    rows[0]["fields"]["匹配店铺"] = "跨境4；本土2店"
    assert plan(rows)["count"] == 0
