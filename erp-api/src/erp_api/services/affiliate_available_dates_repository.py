"""Dates evidenced by complete local affiliate snapshots and live overview runs."""

from datetime import date, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from erp_api.models.affiliate_creator import AffiliateCreatorReport
from erp_api.models.analytics_sync import AnalyticsSyncRun
from erp_api.models.shop import Shop


async def latest_available_dates(
    database, tenant_id: UUID, shop_id: UUID
) -> dict[str, date]:
    async for session in database.session(tenant_id):
        timezone = await session.scalar(
            select(Shop.timezone).where(
                Shop.tenant_id == tenant_id,
                Shop.id == shop_id,
                Shop.status == "active",
            )
        )
        if timezone is None:
            return {}
        creator_day = await session.scalar(
            select(func.max(AffiliateCreatorReport.period_end)).where(
                AffiliateCreatorReport.tenant_id == tenant_id,
                AffiliateCreatorReport.shop_id == shop_id,
                AffiliateCreatorReport.status == "complete",
            )
        )
        video_day = await _analytics_day(session, tenant_id, shop_id, "affiliate_video")
        video_end = await session.scalar(
            select(func.max(AnalyticsSyncRun.window_end)).where(
                AnalyticsSyncRun.tenant_id == tenant_id,
                AnalyticsSyncRun.shop_id == shop_id,
                AnalyticsSyncRun.resource_type == "affiliate_video",
                AnalyticsSyncRun.account_type == "AFFILIATE_ACCOUNTS",
                AnalyticsSyncRun.status == "succeeded",
                AnalyticsSyncRun.fetched_count == AnalyticsSyncRun.persisted_count,
                AnalyticsSyncRun.fetched_count >= 0,
            )
        )
        if video_end is not None:
            local_end = video_end.astimezone(ZoneInfo(timezone))
            if local_end.hour == local_end.minute == local_end.second == local_end.microsecond == 0:
                captured_day = local_end.date() - timedelta(days=1)
                video_day = max(video_day, captured_day) if video_day else captured_day
        live_day = await _analytics_day(session, tenant_id, shop_id, "live")
        return {
            resource: value
            for resource, value in (
                ("creators", creator_day),
                ("videos", video_day),
                ("liveAccounts", live_day),
            )
            if value is not None
        }
    raise RuntimeError("Tenant database session was not created.")


async def _analytics_day(session, tenant_id: UUID, shop_id: UUID, resource: str):
    return await session.scalar(
        select(func.max(AnalyticsSyncRun.latest_available_date)).where(
            AnalyticsSyncRun.tenant_id == tenant_id,
            AnalyticsSyncRun.shop_id == shop_id,
            AnalyticsSyncRun.resource_type == resource,
            AnalyticsSyncRun.account_type == "AFFILIATE_ACCOUNTS",
            AnalyticsSyncRun.status == "succeeded",
        )
    )
