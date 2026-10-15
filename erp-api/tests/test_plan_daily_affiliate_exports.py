"""Rolling export plans reuse complete historical intervals."""

from datetime import date

from scripts.plan_daily_affiliate_exports import (
    creator_missing_windows,
    missing_windows,
    rolling_windows,
)


def test_rolling_windows_cover_two_months_without_gaps():
    windows = rolling_windows(date(2026, 10, 8))
    assert windows == [
        (date(2026, 8, 8), date(2026, 9, 6)),
        (date(2026, 9, 7), date(2026, 10, 6)),
        (date(2026, 10, 7), date(2026, 10, 8)),
    ]


def test_only_uncovered_tail_is_exported():
    rows = [
        {
            "shop": "跨境3", "resource": "video", "status": "succeeded",
            "window": (start, end), "fetched": 12, "persisted": 12,
        }
        for start, end in rolling_windows(date(2026, 10, 7))
    ]
    assert missing_windows("跨境3", "videos", date(2026, 10, 8), rows) == [
        {"resource": "videos", "start": "2026-10-07", "end": "2026-10-08"}
    ]


def test_creator_overlap_is_not_a_valid_rolling_total():
    cutoff = date(2026, 10, 8)
    reports = {(date(2026, 10, 7), cutoff)}

    assert creator_missing_windows(cutoff, reports) == [
        {"resource": "creators", "start": "2026-08-08", "end": "2026-09-06"},
        {"resource": "creators", "start": "2026-09-07", "end": "2026-10-06"},
    ]
    assert creator_missing_windows(
        cutoff, reports | set(rolling_windows(cutoff))
    ) == []


def test_mismatched_totals_do_not_count_as_coverage():
    rows = [
        {
            "shop": "跨境3", "resource": "video", "status": "succeeded",
            "window": (date(2026, 10, 7), date(2026, 10, 8)),
            "fetched": 12, "persisted": 11,
        }
    ]
    assert missing_windows("跨境3", "videos", date(2026, 10, 8), rows)[-1] == {
        "resource": "videos", "start": "2026-10-07", "end": "2026-10-08",
    }
