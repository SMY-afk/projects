from datetime import UTC, date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from erp_api.services.video_ranges import validate_video_window

AnalyticsSyncMode = Literal["initial", "incremental"]


class AnalyticsSyncWindowError(ValueError):
    """Raised when an analytics job cannot form a bounded reporting window."""


def resolve_incremental_window(
    committed_cursor: str | None,
    shop_timezone: ZoneInfo,
    *,
    schedule_mode: Literal["hourly", "daily"],
    initial_sync_days: int,
) -> tuple[datetime, datetime, AnalyticsSyncMode] | None:
    local_now = datetime.now(UTC).astimezone(shop_timezone)
    if schedule_mode == "hourly":
        end = local_now.replace(minute=0, second=0, microsecond=0).astimezone(UTC)
    else:
        end = local_now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(
            UTC
        )
    if committed_cursor is None:
        start = initial_window_start(end, shop_timezone, initial_sync_days)
        return start, end, "initial"
    try:
        start = datetime.fromisoformat(committed_cursor)
    except ValueError as error:
        raise AnalyticsSyncWindowError(
            "Analytics cursor is not a UTC ISO 8601 watermark."
        ) from error
    if start.tzinfo is None or start.utcoffset() is None:
        raise AnalyticsSyncWindowError(
            "Analytics cursor is not a UTC ISO 8601 watermark."
        )
    start = start.astimezone(UTC)
    return None if end <= start else (start, end, "incremental")


def initial_window_start(
    end: datetime, shop_timezone: ZoneInfo, initial_sync_days: int
) -> datetime:
    return (
        end.astimezone(shop_timezone) - timedelta(days=initial_sync_days)
    ).astimezone(UTC)


def resolve_explicit_window(
    window_start: datetime,
    window_end: datetime,
    shop_timezone: ZoneInfo,
) -> tuple[datetime, datetime]:
    try:
        resolved = validate_video_window(
            window_start=window_start,
            window_end=window_end,
            shop_timezone=shop_timezone.key,
            now=datetime.now(UTC),
        )
    except ValueError as error:
        raise AnalyticsSyncWindowError(str(error)) from error
    return resolved.window_start, resolved.window_end


def platform_dates(
    start: datetime,
    end: datetime,
    shop_timezone: ZoneInfo,
    *,
    explicit_window: bool,
    schedule_mode: Literal["hourly", "daily"],
) -> tuple[date, date]:
    start_date = start.astimezone(shop_timezone).date()
    end_date = end.astimezone(shop_timezone).date()
    if not explicit_window and schedule_mode == "hourly":
        end_date += timedelta(days=1)
    return start_date, end_date


def failure_state(
    category: str, attempt: int, max_attempts: int
) -> Literal["retry_wait", "dead_letter", "failed"]:
    if attempt < 1 or max_attempts < 1:
        raise ValueError("attempt and max_attempts must be positive.")
    if category not in {"rate_limited", "timeout", "transport_error"}:
        return "failed"
    return "retry_wait" if attempt < max_attempts else "dead_letter"
