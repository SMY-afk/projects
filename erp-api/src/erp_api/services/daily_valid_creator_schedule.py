"""Isolated Beijing 01:30 table-update cycles, independent of source capture."""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

BEIJING = ZoneInfo("Asia/Shanghai")
DAILY_VALID_CREATOR_UPDATE_TIME = time(1, 30)


def daily_valid_creator_write_day(now: datetime) -> date:
    """Return the last Beijing calendar day whose 01:30 update is due."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Daily valid creator schedule clock must include a UTC offset")
    local = now.astimezone(BEIJING)
    before_update = local.time().replace(tzinfo=None) < DAILY_VALID_CREATOR_UPDATE_TIME
    return local.date() - timedelta(days=int(before_update))


def daily_valid_creator_source_batch(now: datetime) -> date:
    """The due table-update day consumes the preceding source-capture batch."""
    return daily_valid_creator_write_day(now) - timedelta(days=1)


def validate_daily_valid_creator_source_batch(batch: date, now: datetime) -> None:
    """Refuse stale queued jobs or reads crossing into a newer write cycle."""
    if batch != daily_valid_creator_source_batch(now):
        raise ValueError("Daily valid creator schedule changed before write")
