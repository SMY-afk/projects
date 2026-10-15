from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from scripts.daily_affiliate_batch_status import task_row


def test_batch_status_exposes_shop_cutoff_window_and_run_identity() -> None:
    shop_id, run_id = uuid4(), uuid4()
    run = SimpleNamespace(
        id=run_id,
        shop_id=shop_id,
        job_id=(
            f"affiliate-schedule:20261005:20261003:{shop_id}:creator:"
            f"20260803-20260901:a1:{run_id}"
        ),
        window_start=datetime(2026, 8, 3, 7, tzinfo=UTC),
        window_end=datetime(2026, 9, 2, 7, tzinfo=UTC),
        status="succeeded",
        fetched_count=12,
        persisted_count=12,
    )
    row = task_row(run, "fanfu toy tool", "America/Los_Angeles")
    assert row == {
        "shop": "跨境3",
        "resource": "creator",
        "cutoff": "2026-10-03",
        "window": ["2026-08-03", "2026-09-01"],
        "runId": str(run_id),
        "status": "succeeded",
        "fetchedCount": 12,
        "persistedCount": 12,
    }
    run.job_id = run.job_id.replace("20260803-20260901", "20260804-20260901")
    with pytest.raises(ValueError, match="window identity mismatch"):
        task_row(run, "fanfu toy tool", "America/Los_Angeles")


def test_batch_status_includes_affiliate_live_chunks() -> None:
    shop_id, run_id = uuid4(), uuid4()
    run = SimpleNamespace(
        id=run_id,
        shop_id=shop_id,
        job_id=(f"affiliate:live-batch:20261005:{shop_id}:20261003:20260803-20260901"),
        window_start=datetime(2026, 8, 3, 7, tzinfo=UTC),
        window_end=datetime(2026, 9, 2, 7, tzinfo=UTC),
        status="queued",
        fetched_count=0,
        persisted_count=0,
    )
    row = task_row(run, "fanfu toy tool", "America/Los_Angeles")
    assert (row["shop"], row["resource"], row["cutoff"]) == (
        "跨境3",
        "live",
        "2026-10-03",
    )
