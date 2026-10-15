from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

VideoRangePreset = Literal["today", "last7d", "last30d", "custom"]


@dataclass(frozen=True)
class ResolvedVideoRange:
    window_start: datetime
    window_end: datetime
    shop_timezone: str
    is_partial: bool

    @property
    def platform_start_date(self) -> date:
        return self.window_start.astimezone(ZoneInfo(self.shop_timezone)).date()

    @property
    def platform_end_date(self) -> date:
        return self.window_end.astimezone(ZoneInfo(self.shop_timezone)).date()


def resolve_video_range(
    *,
    preset: VideoRangePreset,
    shop_timezone: str,
    now: datetime,
    custom_from: date | None = None,
    custom_to: date | None = None,
) -> ResolvedVideoRange:
    timezone = _timezone(shop_timezone)
    aware_now = _aware(now, "now")
    local_today = aware_now.astimezone(timezone).date()
    if preset == "custom":
        if custom_from is None or custom_to is None:
            raise ValueError("custom range requires both start and end dates")
        start_date, end_date = custom_from, custom_to
        _validate_custom_dates(start_date, end_date, local_today)
    else:
        days = {"today": 1, "last7d": 7, "last30d": 30}.get(preset)
        if days is None:
            raise ValueError("unsupported video range preset")
        start_date = local_today - timedelta(days=days - 1)
        end_date = local_today
    return _calendar_range(start_date, end_date, timezone, aware_now)


def validate_video_window(
    *,
    window_start: datetime,
    window_end: datetime,
    shop_timezone: str,
    now: datetime,
) -> ResolvedVideoRange:
    timezone = _timezone(shop_timezone)
    start = _aware(window_start, "from")
    end = _aware(window_end, "to")
    if end <= start:
        raise ValueError("to must be later than from")
    local_start = start.astimezone(timezone)
    local_end = end.astimezone(timezone)
    if local_start.timetz().replace(tzinfo=None) != time.min:
        raise ValueError("from must be midnight in the shop timezone")
    if local_end.timetz().replace(tzinfo=None) != time.min:
        raise ValueError("to must be exclusive midnight in the shop timezone")
    start_date = local_start.date()
    inclusive_end = local_end.date() - timedelta(days=1)
    local_today = _aware(now, "now").astimezone(timezone).date()
    _validate_custom_dates(start_date, inclusive_end, local_today)
    return _calendar_range(start_date, inclusive_end, timezone, _aware(now, "now"))


def _calendar_range(
    start_date: date,
    inclusive_end: date,
    timezone: ZoneInfo,
    now: datetime,
) -> ResolvedVideoRange:
    start = datetime.combine(start_date, time.min, timezone).astimezone(UTC)
    end = datetime.combine(
        inclusive_end + timedelta(days=1), time.min, timezone
    ).astimezone(UTC)
    return ResolvedVideoRange(
        window_start=start,
        window_end=end,
        shop_timezone=timezone.key,
        is_partial=inclusive_end >= now.astimezone(timezone).date(),
    )


def _validate_custom_dates(start: date, end: date, today: date) -> None:
    if end > today:
        raise ValueError("video range must not include future dates")
    if start > end:
        raise ValueError("start date must not be after end date")
    if (end - start).days + 1 > 30:
        raise ValueError("video range must not exceed 30 days")


def _aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a UTC offset")
    if field_name in {"from", "to"} and value.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must use UTC")
    return value.astimezone(UTC)


def _timezone(value: str) -> ZoneInfo:
    try:
        return ZoneInfo(value)
    except ZoneInfoNotFoundError as error:
        raise ValueError("shop timezone is invalid") from error
