"""A matched shop is a row dimension; aggregated totals must not be copied."""

from datetime import date

import pytest

from scripts.daily_valid_creator_core import SHOP_ORDER
from scripts.daily_valid_creator_shop_rows import desired_shop_rows, shop_record_key


def inputs():
    base = {("abc", shop): {"account": "@ABC", "bd": "BD",
            "sample_day": date(2026, 10, 10), "conflict": False} for shop in ("跨境3", "跨境7")}
    high = {name: {"creators": [], "videos": [], "liveAccounts": []} for name in SHOP_ORDER}
    low = {name: {"creators": [], "videos": [], "liveAccounts": []} for name in SHOP_ORDER}
    windows = {name: {section: (date(2026, 8, 12), date(2026, 10, 12))
               for section in ("creators", "videos", "liveAccounts")} for name in SHOP_ORDER}
    high["跨境3"]["creators"] = [{"username": "abc", "affiliateGmvMinor": 10000}]
    high["跨境7"]["creators"] = [{"username": "@ABC", "affiliateGmvMinor": 20000}]
    return base, high, low, windows


def test_two_matched_shops_produce_two_rows_with_separate_metrics():
    rows = desired_shop_rows(*inputs(), sample_window=(date(2026, 8, 15), date(2026, 10, 13)))
    assert len(rows) == 2
    by_shop = {row["匹配店铺"]: row for row in rows.values()}
    assert by_shop["跨境3"]["业绩"] == 100
    assert by_shop["跨境7"]["业绩"] == 200
    assert sum(row["业绩"] for row in rows.values()) == 300


def test_each_shop_has_a_distinct_stable_identity():
    fields = {"产品线": "童车", "账号名称": " @ABC\u200b ", "匹配店铺": "跨境3"}
    first = shop_record_key(fields)
    second = shop_record_key(fields | {"匹配店铺": "跨境7"})
    assert first != second
    assert first == ("abc", "跨境3")


def test_combined_or_unknown_shops_are_rejected():
    for label in ("跨境3；跨境7", "unknown"):
        with pytest.raises(ValueError, match="exactly one"):
            shop_record_key({"产品线": "童车", "账号名称": "abc", "匹配店铺": label})


def test_local_shop_display_alias_preserves_same_identity():
    fields = {"产品线": "遥控车", "账号名称": "abc", "匹配店铺": "本土店"}
    assert shop_record_key(fields) == shop_record_key(fields | {"匹配店铺": "本土2店"})


def test_sample_only_creator_is_not_assigned_an_invented_shop():
    base, high, low, windows = inputs()
    high["跨境3"]["creators"] = high["跨境7"]["creators"] = []
    base = {("abc", ""): next(iter(base.values()))}
    rows = desired_shop_rows(base, high, low, windows, (date(2026, 8, 15), date(2026, 10, 13)))
    assert list(rows) == [("abc", "")]
    assert next(iter(rows.values()))["业绩"] == 0


def test_video_and_live_metrics_stay_with_their_shop():
    base, high, low, windows = inputs()
    low["跨境3"]["videos"] = [{"creatorUsername": "abc", "videoPostTime": "2026-10-11T12:00:00Z"}]
    high["跨境7"]["liveAccounts"] = [{"fields": {"username": "abc", "startTime": "2026-10-11T12:00:00Z"}}]
    rows = desired_shop_rows(base, high, low, windows, (date(2026, 8, 15), date(2026, 10, 13)))
    assert rows[("abc", "跨境3")]["视频数"] == 1
    assert rows[("abc", "跨境3")]["直播数"] == 0
    assert rows[("abc", "跨境7")]["视频数"] == 0
    assert rows[("abc", "跨境7")]["直播数"] == 1


def test_incomplete_five_shop_source_fails_closed():
    base, high, low, windows = inputs()
    del high["跨境7"]
    with pytest.raises(ValueError, match="Complete five-shop"):
        desired_shop_rows(base, high, low, windows, (date(2026, 8, 15), date(2026, 10, 13)))
