from datetime import date, timedelta
from uuid import uuid4

from erp_api.services.affiliate_center_contract import (
    AffiliateCenterQuery,
    AffiliateCenterResource,
)
from erp_api.services.affiliate_video_window_coverage import (
    select_complete_video_chunks,
    select_complete_video_window,
)


def _query(start: date, end: date) -> AffiliateCenterQuery:
    return AffiliateCenterQuery(
        resource=AffiliateCenterResource.VIDEOS,
        shop_id=uuid4(),
        window_start=start,
        window_end=end,
        shop_timezone="America/Los_Angeles",
        currency="USD",
        filters={},
    )


def test_uses_complete_daily_snapshots_for_the_requested_window() -> None:
    query = _query(date(2026, 7, 8), date(2026, 7, 10))
    available = {
        (date(2026, 7, 8), date(2026, 7, 8)),
        (date(2026, 7, 9), date(2026, 7, 9)),
        (date(2026, 7, 10), date(2026, 7, 10)),
    }

    coverage = select_complete_video_window(query, available)

    assert coverage.window == (date(2026, 7, 8), date(2026, 7, 10))
    assert coverage.missing_dates == ()


def test_uses_daily_snapshots_and_a_complete_chunk_for_the_requested_window() -> None:
    query = _query(date(2026, 7, 8), date(2026, 9, 5))
    first_half_daily = {
        (date(2026, 7, 8) + timedelta(days=offset),) * 2
        for offset in range(30)
    }
    available = first_half_daily | {(date(2026, 8, 7), date(2026, 9, 5))}

    coverage = select_complete_video_window(query, available)
    chunks = select_complete_video_chunks(query, available)

    assert coverage.window == (date(2026, 7, 8), date(2026, 9, 5))
    assert coverage.missing_dates == ()
    assert chunks is not None
    assert len(chunks) == 31
    assert (chunks[-1].window_start, chunks[-1].window_end) == (
        date(2026, 8, 7),
        date(2026, 9, 5),
    )


def test_shifts_to_latest_complete_sixty_day_snapshot_composition() -> None:
    query = _query(date(2026, 7, 8), date(2026, 9, 5))
    available = {
        (date(2026, 7, 4), date(2026, 8, 2)),
        (date(2026, 8, 3), date(2026, 9, 1)),
        (date(2026, 9, 2), date(2026, 9, 2)),
        (date(2026, 9, 3), date(2026, 9, 3)),
        (date(2026, 9, 4), date(2026, 9, 4)),
        (date(2026, 9, 5), date(2026, 9, 5)),
    }

    coverage = select_complete_video_window(query, available)

    assert coverage.window == (date(2026, 7, 4), date(2026, 9, 1))
    assert coverage.missing_dates == ()


def test_reports_each_missing_daily_snapshot_when_no_window_is_complete() -> None:
    query = _query(date(2026, 7, 8), date(2026, 7, 10))
    available = {(date(2026, 7, 8), date(2026, 7, 8))}

    coverage = select_complete_video_window(query, available)

    assert coverage.window is None
    assert coverage.missing_dates == (date(2026, 7, 9), date(2026, 7, 10))
