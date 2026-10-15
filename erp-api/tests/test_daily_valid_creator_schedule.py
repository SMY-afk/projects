"""The daily Feishu write clock does not alter five-shop source capture."""

from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from erp_api.services import affiliate_schedule_queries as source_schedule
from erp_api.services.daily_valid_creator_schedule import (
    DAILY_VALID_CREATOR_UPDATE_TIME,
    daily_valid_creator_source_batch,
    daily_valid_creator_write_day,
    validate_daily_valid_creator_source_batch,
)

BEIJING = ZoneInfo("Asia/Shanghai")


@pytest.mark.parametrize("clock,write_day,source_batch", [
    ("2026-10-14T01:29:59+08:00", "2026-10-13", "2026-10-12"),
    ("2026-10-14T01:30:00+08:00", "2026-10-14", "2026-10-13"),
    ("2026-10-14T23:49:59+08:00", "2026-10-14", "2026-10-13"),
    ("2026-10-14T23:50:00+08:00", "2026-10-14", "2026-10-13"),
    ("2026-10-15T00:00:00+08:00", "2026-10-14", "2026-10-13"),
    ("2026-10-15T01:29:59+08:00", "2026-10-14", "2026-10-13"),
    ("2026-10-15T01:30:00+08:00", "2026-10-15", "2026-10-14"),
    ("2026-10-14T17:29:59+00:00", "2026-10-14", "2026-10-13"),
    ("2026-10-14T17:30:00+00:00", "2026-10-15", "2026-10-14"),
    ("2027-01-01T00:30:00+08:00", "2026-12-31", "2026-12-30"),
    ("2027-01-01T01:30:00+08:00", "2027-01-01", "2026-12-31"),
    ("2028-03-01T01:30:00+08:00", "2028-03-01", "2028-02-29"),
])
def test_update_day_maps_to_previous_source_batch(clock, write_day, source_batch):
    now = datetime.fromisoformat(clock)
    assert daily_valid_creator_write_day(now) == date.fromisoformat(write_day)
    assert daily_valid_creator_source_batch(now) == date.fromisoformat(source_batch)
    validate_daily_valid_creator_source_batch(date.fromisoformat(source_batch), now)


@pytest.mark.parametrize("function", [
    daily_valid_creator_write_day, daily_valid_creator_source_batch,
])
def test_naive_datetime_is_rejected(function):
    with pytest.raises(ValueError, match="UTC offset"):
        function(datetime(2026, 10, 14, 1, 30))  # noqa: DTZ001 - Intentional invalid clock.


def test_stale_batch_is_rejected_at_the_exact_next_update_boundary():
    old_batch = date(2026, 10, 13)
    before = datetime(2026, 10, 15, 1, 29, 59, tzinfo=BEIJING)
    after = datetime(2026, 10, 15, 1, 30, tzinfo=BEIJING)
    validate_daily_valid_creator_source_batch(old_batch, before)
    with pytest.raises(ValueError, match="schedule changed"):
        validate_daily_valid_creator_source_batch(old_batch, after)


def test_source_collection_schedule_is_unchanged_and_separate():
    assert DAILY_VALID_CREATOR_UPDATE_TIME == time(1, 30)
    assert source_schedule.DAILY_RUN_TIME == time(23, 30)
    now = datetime(2026, 10, 14, 15, 50, tzinfo=UTC)
    assert source_schedule.daily_collection_window_open(now)
    assert source_schedule.latest_due_schedule_date(now) == date(2026, 10, 14)
    assert daily_valid_creator_source_batch(now) == date(2026, 10, 13)
