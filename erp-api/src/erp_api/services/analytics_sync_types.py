from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from erp_api.models.analytics_sync import AnalyticsSyncRun

AnalyticsSyncStatus = Literal[
    "queued",
    "running",
    "retry_wait",
    "succeeded",
    "partial",
    "failed",
    "dead_letter",
    "cancelled",
]


@dataclass(frozen=True)
class StoredAnalyticsCursor:
    committed_cursor: str | None
    last_success_at: datetime | None
    fresh_at: datetime | None


@dataclass(frozen=True)
class AnalyticsSyncResult:
    run_id: UUID
    shop_id: UUID
    resource_type: str
    job_id: str
    status: str
    attempt_count: int
    fetched_count: int
    persisted_count: int
    recovery_cursor: str | None
    error_category: str | None
    error_summary: str | None
    fresh_at: datetime | None


def normalize_sync_window(
    window_start: datetime, window_end: datetime
) -> tuple[datetime, datetime]:
    start, end = optional_utc(window_start), optional_utc(window_end)
    if start is None or end is None or end <= start:
        raise ValueError("Sync windows must be a non-empty UTC range.")
    return start, end


def optional_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must include a UTC offset.")
    return value.astimezone(UTC)


def bounded(value: str | None, length: int) -> str | None:
    return value[:length] if value else None


def failure_summary(category: str) -> str:
    summaries = {
        "invalid_response": "Analytics platform response was invalid.",
        "missing_field": "Analytics platform response missed a required field.",
        "platform_error": "Analytics platform request failed.",
        "rate_limited": "Analytics platform rate limit was reached.",
        "timeout": "Analytics platform request timed out.",
        "transport_error": "Analytics platform transport failed.",
    }
    return summaries[category]


def partial_summary(reason: str) -> str:
    summaries = {
        "total_count_mismatch": "Affiliate record total did not match the source total.",
        "cursor_interrupted": "Affiliate pagination cursor was interrupted.",
        "page_failed": "One or more affiliate pages failed.",
    }
    try:
        return summaries[reason]
    except KeyError as error:
        raise ValueError("Unsupported affiliate partial reason.") from error


def sync_result(
    run: AnalyticsSyncRun, fresh_at: datetime | None
) -> AnalyticsSyncResult:
    return AnalyticsSyncResult(
        run_id=run.id,
        shop_id=run.shop_id,
        resource_type=run.resource_type,
        job_id=run.job_id,
        status=run.status,
        attempt_count=run.attempt_count,
        fetched_count=run.fetched_count,
        persisted_count=run.persisted_count,
        recovery_cursor=run.recovery_cursor,
        error_category=run.error_category,
        error_summary=run.error_summary,
        fresh_at=fresh_at,
    )
