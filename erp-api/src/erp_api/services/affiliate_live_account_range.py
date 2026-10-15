from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

AffiliateLiveRangePreset = Literal[
    "today", "last7d", "last30d", "last60d", "custom"
]


@dataclass(frozen=True)
class AffiliateLiveRange:
    window_start: datetime
    window_end: datetime


def resolve_live_range(
    preset: AffiliateLiveRangePreset,
    shop_timezone: str,
    now: datetime,
    *,
    custom_from: date | None = None,
    custom_to: date | None = None,
) -> AffiliateLiveRange:
    try:
        timezone = ZoneInfo(shop_timezone)
    except ZoneInfoNotFoundError as error:
        raise ValueError("shop timezone is invalid") from error
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must include a UTC offset")
    local_today = now.astimezone(timezone).date()
    if preset == "custom":
        if custom_from is None or custom_to is None:
            raise ValueError("custom range requires both dates")
        if custom_from > custom_to:
            raise ValueError("custom start date must not be after end date")
        if custom_to > local_today:
            raise ValueError("custom range must not include future dates")
        start_date, end_date = custom_from, custom_to
    else:
        days = {"today": 1, "last7d": 7, "last30d": 30, "last60d": 60}[
            preset
        ]
        start_date = local_today - timedelta(days=days - 1)
        end_date = local_today
    return AffiliateLiveRange(
        window_start=datetime.combine(start_date, time.min, timezone).astimezone(UTC),
        window_end=datetime.combine(
            end_date + timedelta(days=1), time.min, timezone
        ).astimezone(UTC),
    )


def split_live_range(
    live_range: AffiliateLiveRange,
    shop_timezone: str,
    *,
    max_days: int = 30,
) -> list[AffiliateLiveRange]:
    if max_days < 1:
        raise ValueError("max_days must be positive")
    try:
        timezone = ZoneInfo(shop_timezone)
    except ZoneInfoNotFoundError as error:
        raise ValueError("shop timezone is invalid") from error
    start_date = live_range.window_start.astimezone(timezone).date()
    end_date = live_range.window_end.astimezone(timezone).date()
    chunks = []
    while start_date < end_date:
        chunk_end = min(start_date + timedelta(days=max_days), end_date)
        chunks.append(
            AffiliateLiveRange(
                window_start=datetime.combine(
                    start_date, time.min, timezone
                ).astimezone(UTC),
                window_end=datetime.combine(
                    chunk_end, time.min, timezone
                ).astimezone(UTC),
            )
        )
        start_date = chunk_end
    return chunks
