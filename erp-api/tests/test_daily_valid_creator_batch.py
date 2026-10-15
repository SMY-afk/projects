from datetime import UTC, date, datetime, timedelta

import pytest

from scripts import daily_valid_creator_batch as batch
from scripts.daily_valid_creator_batch import evaluate_batch, expected_windows
from scripts.daily_valid_creator_core import SHOP_LINES

BATCH = date(2026, 10, 5)
CUTOFFS = {
    name: {
        "creators": date(2026, 10, 3),
        "videos": date(2026, 10, 1),
        "liveAccounts": date(2026, 10, 2),
    }
    for name in SHOP_LINES
}
NOW = datetime(2026, 10, 5, tzinfo=UTC)


def complete_runs() -> list[dict]:
    return [
        {
            "shop": shop,
            "resource": resource,
            "window": (start, end),
            "batch": BATCH,
            "cutoff": CUTOFFS[shop][
                {"creator": "creators", "video": "videos", "live": "liveAccounts"}[
                    resource
                ]
            ],
            "status": "succeeded",
            "fetched": 3,
            "persisted": 3,
            "started_at": NOW,
            "finished_at": NOW + timedelta(minutes=1),
        }
        for shop, resource, start, end in sorted(expected_windows(CUTOFFS))
    ]


def test_complete_five_shop_three_resource_batch_passes() -> None:
    runs = complete_runs()
    assert len(runs) == 45
    result = evaluate_batch(CUTOFFS, BATCH, runs)
    assert result == {
        "batch_date": "2026-10-05",
        "required_windows": 45,
        "reused_windows": 0,
    }


def test_missing_or_pending_window_blocks_preview() -> None:
    runs = complete_runs()
    missing = runs.pop()
    with pytest.raises(ValueError, match="no complete successful capture"):
        evaluate_batch(CUTOFFS, BATCH, runs)
    missing["status"] = "running"
    runs.append(missing)
    with pytest.raises(ValueError, match="current-batch task pending"):
        evaluate_batch(CUTOFFS, BATCH, runs)


def test_mismatched_task_total_and_cutoff_block_preview() -> None:
    runs = complete_runs()
    runs[0]["persisted"] = 2
    with pytest.raises(ValueError, match="fetched/persisted totals differ"):
        evaluate_batch(CUTOFFS, BATCH, runs)
    runs = complete_runs()
    runs[0]["cutoff"] = date(2026, 9, 30)
    with pytest.raises(ValueError, match="cutoff differs"):
        evaluate_batch(CUTOFFS, BATCH, runs)


def test_exact_historical_success_can_be_reused_but_current_failure_cannot() -> None:
    runs = complete_runs()
    runs[0]["batch"] = BATCH - timedelta(days=1)
    runs[0]["cutoff"] = None
    assert evaluate_batch(CUTOFFS, BATCH, runs)["reused_windows"] == 1
    runs.append(
        {
            **runs[0],
            "batch": BATCH,
            "cutoff": CUTOFFS[runs[0]["shop"]][
                {"creator": "creators", "video": "videos", "live": "liveAccounts"}[
                    runs[0]["resource"]
                ]
            ],
            "status": "failed",
        }
    )
    with pytest.raises(ValueError, match="current-batch task did not succeed"):
        evaluate_batch(CUTOFFS, BATCH, runs)


def test_unclaimed_queued_intent_does_not_hide_verified_historical_coverage() -> None:
    runs = complete_runs()
    historical = {**runs[0], "batch": None, "cutoff": None}
    queued = {
        **runs[0], "status": "queued",
        "started_at": NOW + timedelta(minutes=5), "finished_at": None,
    }
    runs[0] = historical

    assert evaluate_batch(CUTOFFS, BATCH, runs + [queued])["reused_windows"] == 1

    running = {**queued, "status": "running"}
    with pytest.raises(ValueError, match="current-batch task pending"):
        evaluate_batch(CUTOFFS, BATCH, runs + [running])


def test_superseded_pending_task_and_other_date_are_ignored() -> None:
    runs = complete_runs()
    previous = {**runs[0], "status": "queued", "started_at": NOW - timedelta(minutes=5)}
    other_date = {
        **runs[0],
        "window": (date(2026, 9, 1), date(2026, 9, 1)),
        "cutoff": date(2026, 9, 1),
        "status": "running",
    }
    assert (
        evaluate_batch(CUTOFFS, BATCH, runs + [previous, other_date])[
            "required_windows"
        ]
        == 45
    )


def test_manual_schedule_job_is_not_parsed_as_current_batch_date() -> None:
    assert (
        batch._job_batch_date(
            "affiliate-schedule:manual-exact-creator-backfill-20260920:run"
        )
        is None
    )
    assert batch._job_batch_date("affiliate-schedule:20261005:run") == BATCH
    assert batch._job_batch_date("affiliate:live-batch:20261005:shop:run") == BATCH


def test_later_exact_repair_supersedes_failed_current_batch_window() -> None:
    runs = complete_runs()
    failed = {**runs[0], "status": "failed"}
    repair = {
        **runs[0],
        "batch": None,
        "cutoff": None,
        "started_at": NOW + timedelta(minutes=5),
        "finished_at": NOW + timedelta(minutes=6),
    }
    runs[0] = failed

    assert evaluate_batch(CUTOFFS, BATCH, runs + [repair])["reused_windows"] == 1


def test_complete_historical_daily_runs_cover_a_required_window() -> None:
    runs = complete_runs()
    original = runs.pop(0)
    start, end = original["window"]
    cursor = start
    while cursor <= end:
        runs.append({
            **original,
            "window": (cursor, cursor),
            "batch": None,
            "cutoff": None,
        })
        cursor += timedelta(days=1)

    assert evaluate_batch(CUTOFFS, BATCH, runs)["reused_windows"] == 1
    runs.pop()
    with pytest.raises(ValueError, match="no complete successful capture"):
        evaluate_batch(CUTOFFS, BATCH, runs)


def test_load_bounds_include_the_latest_local_shop_day() -> None:
    assert batch._query_utc_bounds(date(2026, 8, 7), date(2026, 10, 7)) == (
        datetime(2026, 8, 7, tzinfo=UTC),
        datetime(2026, 10, 8, tzinfo=UTC),
    )
