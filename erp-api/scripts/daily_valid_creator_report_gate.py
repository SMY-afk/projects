"""Require exact complete creator reports before a rolling Feishu update."""

from __future__ import annotations

from datetime import date, timedelta

from dateutil.relativedelta import relativedelta
from sqlalchemy import select

from erp_api.core.config import get_settings
from erp_api.models.affiliate_creator import AffiliateCreatorReport
from erp_api.services.affiliate_local_export_service import TARGET_SHOPS
from erp_api.workers.affiliate_live_schedule import _active_live_shops

BUSINESS_NAMES = {target.source_name: target.business_name for target in TARGET_SHOPS}


def rolling_windows(cutoff: date) -> list[tuple[date, date]]:
    start = cutoff - relativedelta(months=2)
    windows = []
    while start <= cutoff:
        end = min(start + timedelta(days=29), cutoff)
        windows.append((start, end))
        start = end + timedelta(days=1)
    return windows


def creator_missing_windows(
    cutoff: date, reports: set[tuple[date, date]]
) -> list[dict[str, str]]:
    start = cutoff - relativedelta(months=2)
    if (start, cutoff) in reports:
        return []
    bounded = rolling_windows(cutoff)
    if all(window in reports for window in bounded):
        return []
    compass = []
    cursor = start
    while cursor <= cutoff:
        remaining = (cutoff - cursor).days + 1
        days = 30 if remaining >= 30 else 7 if remaining >= 7 else 1
        end = cursor + timedelta(days=days - 1)
        compass.append((cursor, end))
        cursor = end + timedelta(days=1)
    if all(window in reports for window in compass):
        return []
    if all((day, day) in reports for day in _days(start, cutoff)):
        return []
    return [
        {"resource": "creators", "start": first.isoformat(), "end": last.isoformat()}
        for first, last in bounded
        if (first, last) not in reports
    ]


def _days(start: date, end: date):
    while start <= end:
        yield start
        start += timedelta(days=1)


async def creator_report_windows(database, shop, cutoff: date) -> set[tuple[date, date]]:
    async with database.system_session_factory() as session:
        rows = (
            await session.scalars(
                select(AffiliateCreatorReport).where(
                    AffiliateCreatorReport.tenant_id == shop.tenant_id,
                    AffiliateCreatorReport.shop_id == shop.shop_id,
                    AffiliateCreatorReport.period_start >= cutoff - relativedelta(months=2),
                    AffiliateCreatorReport.period_end <= cutoff,
                    AffiliateCreatorReport.shop_timezone == shop.timezone,
                    AffiliateCreatorReport.currency == shop.currency,
                    AffiliateCreatorReport.status == "complete",
                )
            )
        ).all()
    return {
        (row.period_start, row.period_end)
        for row in rows
        if row.completeness_reason == "complete"
        and row.expected_total == row.records_received
    }


async def missing_creator_reports(database, cutoffs) -> dict[str, list[dict[str, str]]]:
    tenant_id = get_settings().affiliate_export_tenant_id
    shops = [
        shop for shop in await _active_live_shops(database)
        if shop.tenant_id == tenant_id and shop.source_name in BUSINESS_NAMES
    ]
    if len(shops) != len(TARGET_SHOPS) or {
        shop.source_name for shop in shops
    } != set(BUSINESS_NAMES) or set(cutoffs) != set(BUSINESS_NAMES.values()):
        raise RuntimeError("Exact five authorized creator sources are unavailable")
    missing = {}
    for shop in shops:
        name = BUSINESS_NAMES[shop.source_name]
        cutoff = cutoffs[name]["creators"]
        windows = await creator_report_windows(database, shop, cutoff)
        due = creator_missing_windows(cutoff, windows)
        if due:
            missing[name] = due
    return missing
