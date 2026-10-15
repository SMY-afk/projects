from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

RealtimeRange = Literal["today", "last24h"]
TrendRange = Literal["last7d", "last30d", "lastMonth", "year"]
OrderRange = Literal["last7d", "last14d", "last28d"]


@dataclass(frozen=True)
class TimeWindow:
    start: datetime
    end: datetime


@dataclass(frozen=True)
class ComparisonWindows:
    current: TimeWindow
    previous: TimeWindow
    last_year: TimeWindow


def timezone_or_utc(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as error:
        raise ValueError("timezone must be a valid IANA timezone.") from error


def realtime_windows(
    kind: RealtimeRange, timezone: ZoneInfo, now: datetime | None = None
) -> ComparisonWindows:
    current_end = (now or datetime.now(UTC)).astimezone(timezone)
    current_start = (
        current_end.replace(hour=0, minute=0, second=0, microsecond=0)
        if kind == "today"
        else current_end - timedelta(hours=24)
    )
    duration = current_end - current_start
    return ComparisonWindows(
        current=_utc_window(current_start, current_end),
        previous=_utc_window(current_start - duration, current_start),
        last_year=_utc_window(
            current_start - timedelta(days=7), current_end - timedelta(days=7)
        ),
    )


def trend_windows(
    kind: TrendRange, timezone: ZoneInfo, now: datetime | None = None
) -> ComparisonWindows:
    current_end = (now or datetime.now(UTC)).astimezone(timezone)
    today = current_end.replace(hour=0, minute=0, second=0, microsecond=0)
    if kind == "last7d":
        current_start = today - timedelta(days=6)
    elif kind == "last30d":
        current_start = today - timedelta(days=29)
    elif kind == "lastMonth":
        current_end = today.replace(day=1)
        previous_month_end = current_end
        current_start = (previous_month_end - timedelta(days=1)).replace(day=1)
    else:
        current_start = today.replace(month=1, day=1)
    duration = current_end - current_start
    return ComparisonWindows(
        current=_utc_window(current_start, current_end),
        previous=_utc_window(current_start - duration, current_start),
        last_year=_utc_window(
            _shift_year(current_start, -1), _shift_year(current_end, -1)
        ),
    )


def order_window(
    kind: OrderRange, timezone: ZoneInfo, now: datetime | None = None
) -> TimeWindow:
    current_end = (now or datetime.now(UTC)).astimezone(timezone)
    days = {"last7d": 7, "last14d": 14, "last28d": 28}[kind]
    start = current_end.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(
        days=days - 1
    )
    return _utc_window(start, current_end)


def _utc_window(start: datetime, end: datetime) -> TimeWindow:
    return TimeWindow(start=start.astimezone(UTC), end=end.astimezone(UTC))


def _shift_year(value: datetime, years: int) -> datetime:
    try:
        return value.replace(year=value.year + years)
    except ValueError:
        return value.replace(year=value.year + years, day=28)
