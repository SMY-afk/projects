from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, time, timedelta
from functools import cache
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select

from erp_api.models.analytics_sync import AnalyticsSyncRun
from erp_api.services.affiliate_center_contract import AffiliateCenterQuery


@dataclass(frozen=True)
class VideoWindowCoverage:
    window: tuple[date, date] | None
    missing_dates: tuple[date, ...]


async def resolve_complete_video_window(
    session,
    tenant_id: UUID,
    query: AffiliateCenterQuery,
) -> VideoWindowCoverage:
    available = await _complete_video_ranges(session, tenant_id, query)
    return select_complete_video_window(query, available)


async def resolve_complete_video_chunks(
    session,
    tenant_id: UUID,
    query: AffiliateCenterQuery,
) -> list[AffiliateCenterQuery] | None:
    available = await _complete_video_ranges(session, tenant_id, query)
    return select_complete_video_chunks(query, available)


async def _complete_video_ranges(
    session,
    tenant_id: UUID,
    query: AffiliateCenterQuery,
) -> set[tuple[date, date]]:
    rows = (
        await session.execute(
            select(
                AnalyticsSyncRun.window_start,
                AnalyticsSyncRun.window_end,
            ).where(
                AnalyticsSyncRun.tenant_id == tenant_id,
                AnalyticsSyncRun.shop_id == query.shop_id,
                AnalyticsSyncRun.resource_type == "affiliate_video",
                AnalyticsSyncRun.account_type == "AFFILIATE_ACCOUNTS",
                AnalyticsSyncRun.currency == query.currency,
                AnalyticsSyncRun.status == "succeeded",
            )
        )
    ).all()
    timezone = ZoneInfo(query.shop_timezone)
    available = {
        local_range
        for row in rows
        if (local_range := _local_date_range(row.window_start, row.window_end, timezone))
    }
    return available


def select_complete_video_window(
    query: AffiliateCenterQuery,
    available: set[tuple[date, date]],
) -> VideoWindowCoverage:
    span = query.window_end - query.window_start
    candidate_ends = sorted(
        {end for _, end in available if end <= query.window_end},
        reverse=True,
    )
    for candidate_end in candidate_ends:
        candidate_start = candidate_end - span
        candidate = replace(
            query,
            window_start=candidate_start,
            window_end=candidate_end,
        )
        if select_complete_video_chunks(candidate, available) is not None:
            return VideoWindowCoverage((candidate_start, candidate_end), ())
    return VideoWindowCoverage(
        None,
        tuple(_missing_daily_dates(query.window_start, query.window_end, available)),
    )


def select_complete_video_chunks(
    query: AffiliateCenterQuery,
    available: set[tuple[date, date]],
) -> list[AffiliateCenterQuery] | None:
    ranges_by_start: dict[date, list[tuple[date, date]]] = {}
    for start, end in available:
        if query.window_start <= start <= end <= query.window_end:
            ranges_by_start.setdefault(start, []).append((start, end))
    for ranges in ranges_by_start.values():
        ranges.sort(key=lambda item: item[1], reverse=True)

    after_window = query.window_end + timedelta(days=1)

    @cache
    def visit(current: date) -> tuple[tuple[date, date], ...] | None:
        if current == after_window:
            return ()
        best: tuple[tuple[date, date], ...] | None = None
        for item in ranges_by_start.get(current, []):
            remainder = visit(item[1] + timedelta(days=1))
            if remainder is None:
                continue
            candidate = (item, *remainder)
            if best is None or len(candidate) < len(best):
                best = candidate
        return best

    selected = visit(query.window_start)
    if selected is None:
        return None
    return [
        replace(query, window_start=start, window_end=end) for start, end in selected
    ]


def _missing_daily_dates(
    start: date,
    end: date,
    available: set[tuple[date, date]],
):
    current = start
    while current <= end:
        if (current, current) not in available:
            yield current
        current += timedelta(days=1)


def _local_date_range(start, end, timezone: ZoneInfo) -> tuple[date, date] | None:
    local_start = start.astimezone(timezone)
    local_end = end.astimezone(timezone)
    if local_start.time() != time.min or local_end.time() != time.min:
        return None
    return local_start.date(), local_end.date() - timedelta(days=1)
