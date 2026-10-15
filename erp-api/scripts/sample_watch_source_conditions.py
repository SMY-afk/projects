"""Select a successful source run for the actual available shop day."""

from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

from erp_api.models.analytics_sync import AnalyticsSyncRun


def successful_source_conditions(
    resource: str, available: dict[str, date | None], timezone: str | None
) -> tuple:
    if resource == "live":
        day = available.get("liveAccounts")
        if not day or not timezone:
            return (AnalyticsSyncRun.id.is_(None),)
        start = datetime.combine(day, time.min, tzinfo=ZoneInfo(timezone)).astimezone(
            UTC
        )
        return (
            AnalyticsSyncRun.latest_available_date == day,
            AnalyticsSyncRun.window_start <= start,
            AnalyticsSyncRun.window_end > start,
        )
    day = available.get("creators" if resource == "affiliate_creator" else "videos")
    if not day or not timezone:
        return (AnalyticsSyncRun.id.is_(None),)
    start = datetime.combine(day, time.min, tzinfo=ZoneInfo(timezone)).astimezone(UTC)
    return (AnalyticsSyncRun.window_start <= start, AnalyticsSyncRun.window_end > start)
