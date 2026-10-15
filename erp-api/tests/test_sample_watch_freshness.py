from datetime import UTC, date, datetime
from types import SimpleNamespace

from sqlalchemy import select

from erp_api.models.analytics_sync import AnalyticsSyncRun
from scripts.sample_watch_freshness import _analytics_sources_complete
from scripts.sample_watch_source_conditions import successful_source_conditions


def _run(start: str, end: str, *, latest: date | None = None):
    return SimpleNamespace(
        status="succeeded",
        fetched_count=10,
        persisted_count=10,
        window_start=datetime.fromisoformat(start).replace(tzinfo=UTC),
        window_end=datetime.fromisoformat(end).replace(tzinfo=UTC),
        latest_available_date=latest,
    )


def test_successful_windows_cover_available_local_days() -> None:
    successful = {
        "affiliate_creator": _run("2026-08-04T07:00:00", "2026-10-03T07:00:00"),
        "affiliate_video": _run("2026-10-01T07:00:00", "2026-10-02T07:00:00"),
        "live": _run(
            "2026-10-01T07:00:00", "2026-10-03T07:00:00", latest=date(2026, 10, 2)
        ),
    }

    assert _analytics_sources_complete(
        successful,
        {
            "creators": date(2026, 10, 2),
            "videos": date(2026, 10, 1),
            "liveAccounts": date(2026, 10, 2),
        },
        "America/Los_Angeles",
    )


def test_successful_window_must_cover_latest_day_and_be_complete() -> None:
    successful = {
        "affiliate_creator": _run("2026-10-01T07:00:00", "2026-10-02T07:00:00"),
        "affiliate_video": _run("2026-10-01T07:00:00", "2026-10-02T07:00:00"),
        "live": _run(
            "2026-10-01T07:00:00", "2026-10-03T07:00:00", latest=date(2026, 10, 2)
        ),
    }
    available = {
        "creators": date(2026, 10, 2),
        "videos": date(2026, 10, 1),
        "liveAccounts": date(2026, 10, 2),
    }

    assert not _analytics_sources_complete(successful, available, "America/Los_Angeles")
    successful["affiliate_creator"] = _run("2026-10-02T07:00:00", "2026-10-03T07:00:00")
    successful["affiliate_video"].persisted_count = 9
    assert not _analytics_sources_complete(successful, available, "America/Los_Angeles")


def test_source_selection_filters_to_available_day_not_last_finished_day() -> None:
    conditions = successful_source_conditions(
        "affiliate_creator",
        {"creators": date(2026, 10, 2), "videos": date(2026, 10, 1)},
        "America/Los_Angeles",
    )
    sql = str(
        select(AnalyticsSyncRun)
        .where(*conditions)
        .compile(compile_kwargs={"literal_binds": True})
    )
    assert "2026-10-02 07:00:00" in sql
    assert "analytics_sync_runs.window_start <=" in sql
    assert "analytics_sync_runs.window_end >" in sql
