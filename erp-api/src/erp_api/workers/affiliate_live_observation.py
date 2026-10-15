"""Read and publish the independent date returned by TK live overviews."""

from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy import func, select

from erp_api.models.analytics_sync import AnalyticsSyncRun
from erp_api.services.affiliate_capture_health import AffiliateCaptureHealthRepository
from scripts.daily_valid_creator_online import MAX_EVIDENCE_AGE


async def latest_persisted_live_date(
    database, tenant_id: UUID, shop_id: UUID
) -> date | None:
    """Choose a small official-API probe window, not a freshness credential."""
    async with database.system_session_factory() as session:
        return await session.scalar(
            select(func.max(AnalyticsSyncRun.latest_available_date)).where(
                AnalyticsSyncRun.tenant_id == tenant_id,
                AnalyticsSyncRun.shop_id == shop_id,
                AnalyticsSyncRun.resource_type == "live",
                AnalyticsSyncRun.account_type == "AFFILIATE_ACCOUNTS",
                AnalyticsSyncRun.status == "succeeded",
                AnalyticsSyncRun.latest_available_date.is_not(None),
            )
        )


async def latest_recent_live_observation(
    database, tenant_id: UUID, shop_id: UUID, *, now: datetime
) -> tuple[date, datetime] | None:
    """Use a completed official overview, never a creator or requested window date."""
    async with database.system_session_factory() as session:
        conditions = (
            AnalyticsSyncRun.tenant_id == tenant_id,
            AnalyticsSyncRun.shop_id == shop_id,
            AnalyticsSyncRun.resource_type == "live",
            AnalyticsSyncRun.account_type == "AFFILIATE_ACCOUNTS",
            AnalyticsSyncRun.status == "succeeded",
            AnalyticsSyncRun.latest_available_date.is_not(None),
        )
        latest_day = await session.scalar(
            select(func.max(AnalyticsSyncRun.latest_available_date)).where(*conditions)
        )
        row = (
            await session.execute(
                select(
                    AnalyticsSyncRun.latest_available_date,
                    AnalyticsSyncRun.finished_at,
                )
                .where(
                    *conditions,
                    AnalyticsSyncRun.finished_at >= now - MAX_EVIDENCE_AGE,
                    AnalyticsSyncRun.finished_at <= now,
                )
                .order_by(AnalyticsSyncRun.finished_at.desc())
                .limit(1)
            )
        ).one_or_none()
    if row is None or row[0] != latest_day:
        return None
    return row[0], row[1].astimezone(UTC)


async def record_completed_live_date(ctx, tenant_id: UUID, result) -> None:
    if (
        result is None
        or result.resource_type != "live"
        or result.status != "succeeded"
        or result.fetched_count != result.persisted_count
        or ctx.get("redis") is None
    ):
        return
    async with ctx["database"].system_session_factory() as session:
        day = await session.scalar(
            select(AnalyticsSyncRun.latest_available_date).where(
                AnalyticsSyncRun.id == result.run_id,
                AnalyticsSyncRun.tenant_id == tenant_id,
                AnalyticsSyncRun.account_type == "AFFILIATE_ACCOUNTS",
            )
        )
    if day is not None:
        await AffiliateCaptureHealthRepository(ctx["redis"]).record_observation(
            tenant_id, result.shop_id, "liveAccounts", day
        )
