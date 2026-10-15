"""Only real missing stitching intervals should be scheduled for recapture."""

from datetime import date, timedelta

from scripts.plan_daily_affiliate_exports import exact_video_path_missing


def run(start, end, persisted=10):
    return {"shop": "跨境3", "resource": "video", "status": "succeeded",
            "window": (start, end), "fetched": 10, "persisted": persisted}


def test_overlap_coverage_needs_only_final_day_not_two_month_reexport():
    start, end = date(2026, 8, 9), date(2026, 10, 9)
    rows = []
    current = start
    while current <= end - timedelta(days=3):
        rows.append(run(current, current))
        current += timedelta(days=1)
    rows.extend([run(date(2026, 10, 7), date(2026, 10, 8)),
                 run(date(2026, 10, 8), end)])
    assert exact_video_path_missing("跨境3", end, rows) == [
        {"resource": "videos", "start": "2026-10-09", "end": "2026-10-09"}
    ]


def test_exact_path_is_reused_and_incomplete_tail_is_not():
    end = date(2026, 10, 9)
    rows = [run(date(2026, 8, 9), date(2026, 9, 7)),
            run(date(2026, 9, 8), date(2026, 10, 7)),
            run(date(2026, 10, 8), end)]
    assert exact_video_path_missing("跨境3", end, rows) == []
    rows[-1]["persisted"] = 9
    assert exact_video_path_missing("跨境3", end, rows) == [
        {"resource": "videos", "start": "2026-10-08", "end": "2026-10-09"}
    ]
