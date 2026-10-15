from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from arq import Retry
from sqlalchemy import select

from erp_api.models.analytics_sync import AnalyticsSyncRun
from erp_api.models.shop import Shop
from erp_api.models.shop_connection import ShopConnection
from erp_api.services.affiliate_center_contract import (
    AffiliateCenterQuery,
    AffiliateCenterResource,
)
from erp_api.services.affiliate_official_availability import (
    AffiliateOfficialAvailabilityRepository,
)
from erp_api.services.affiliate_source_resolver import (
    is_official_affiliate_connection,
)
from erp_api.services.compass_export_rate_gate import CompassExportDeferred
from erp_api.services.tiktok_transport import TikTokApiError, TikTokRateLimitError


async def sync_official_affiliate_job(
    ctx,
    tenant_id: str,
    shop_id: str,
    resource: str,
    window_start: str,
    window_end: str,
    shop_timezone: str,
    currency: str,
    run_job_id: str,
):
    service = ctx.get("official_affiliate_sync_service")
    if service is None:
        raise RuntimeError("Official affiliate sync service is unavailable.")
    query = AffiliateCenterQuery(
        resource=AffiliateCenterResource(resource),
        shop_id=UUID(shop_id),
        window_start=date.fromisoformat(window_start),
        window_end=date.fromisoformat(window_end),
        shop_timezone=shop_timezone,
        currency=currency,
        filters={},
    )
    try:
        return await service.sync(UUID(tenant_id), query, job_id=run_job_id)
    except CompassExportDeferred as error:
        raise Retry(defer=error.retry_after_seconds) from error
    except TikTokRateLimitError as error:
        defer = error.retry_after_seconds or 3600
        if query.resource is AffiliateCenterResource.CREATORS:
            defer = max(3_600, defer)
        raise Retry(defer=defer) from error
    except TikTokApiError as error:
        if error.code != "13017003":
            raise
        raise Retry(defer=3600) from error


async def enqueue_scheduled_official_affiliate_syncs(ctx) -> int:
    queued = 0
    availability = AffiliateOfficialAvailabilityRepository(ctx["redis"])
    for shop in await _official_shops(ctx["database"]):
        tenant_id, shop_id, timezone, currency = shop
        latest = await availability.get(tenant_id, shop_id)
        if latest is None:
            latest = datetime.now(UTC).date() - timedelta(days=1)
        for window_start, window_end in _rolling_windows(latest):
            for resource in AffiliateCenterResource:
                resource_type = (
                    "affiliate_creator"
                    if resource is AffiliateCenterResource.CREATORS
                    else "affiliate_video"
                )
                if await _has_complete_run(
                    ctx["database"],
                    tenant_id,
                    shop_id,
                    resource_type,
                    window_start,
                    window_end,
                    timezone,
                ):
                    continue
                query = AffiliateCenterQuery(
                    resource=resource,
                    shop_id=shop_id,
                    window_start=window_start,
                    window_end=window_end,
                    shop_timezone=timezone,
                    currency=currency,
                    filters={},
                )
                job_id = (
                    f"official-affiliate-schedule:{shop_id}:{resource.value}:"
                    f"{window_start:%Y%m%d}:{window_end:%Y%m%d}"
                )
                start, end = query.utc_window()
                run_id = await ctx["analytics_sync_repository"].create_run(
                    tenant_id,
                    shop_id,
                    resource_type=resource_type,
                    window_start=start,
                    window_end=end,
                    start_cursor=None,
                    job_id=job_id,
                    currency=currency,
                    account_type="AFFILIATE_ACCOUNTS",
                )
                job = await ctx["redis"].enqueue_job(
                    "sync_official_affiliate_job",
                    str(tenant_id),
                    str(shop_id),
                    resource.value,
                    window_start.isoformat(),
                    window_end.isoformat(),
                    timezone,
                    currency,
                    job_id,
                    _job_id=job_id,
                )
                if job is None:
                    await ctx["analytics_sync_repository"].cancel_run(
                        tenant_id, run_id
                    )
                    continue
                queued += 1
    return queued


async def _official_shops(database) -> list[tuple[UUID, UUID, str, str]]:
    async with database.system_session_factory() as session:
        rows = (
            await session.execute(
                select(
                    Shop.tenant_id,
                    Shop.id,
                    Shop.timezone,
                    Shop.currency,
                    Shop.shop_name,
                    ShopConnection.app_profile,
                    ShopConnection.auth_status,
                    ShopConnection.scopes,
                )
                .join(ShopConnection, ShopConnection.shop_id == Shop.id)
                .where(Shop.platform == "tiktok", Shop.status == "active")
            )
        ).all()
    return [
        (tenant_id, shop_id, timezone, (currency or "USD").upper())
        for tenant_id, shop_id, timezone, currency, shop_name, profile, status, scopes in rows
        if timezone
        and is_official_affiliate_connection(
            {
                "appProfile": profile,
                "status": status,
                "scopes": scopes or [],
                "shopName": shop_name,
            }
        )
    ]


async def _has_complete_run(
    database,
    tenant_id: UUID,
    shop_id: UUID,
    resource_type: str,
    window_start: date,
    window_end: date,
    timezone: str,
) -> bool:
    query = AffiliateCenterQuery(
        resource=AffiliateCenterResource.CREATORS
        if resource_type == "affiliate_creator"
        else AffiliateCenterResource.VIDEOS,
        shop_id=shop_id,
        window_start=window_start,
        window_end=window_end,
        shop_timezone=timezone,
        currency="USD",
        filters={},
    )
    start, end = query.utc_window()
    async for session in database.session(tenant_id):
        run = await session.scalar(
            select(AnalyticsSyncRun.id).where(
                AnalyticsSyncRun.shop_id == shop_id,
                AnalyticsSyncRun.resource_type == resource_type,
                AnalyticsSyncRun.window_start == start,
                AnalyticsSyncRun.window_end == end,
                AnalyticsSyncRun.status == "succeeded",
            )
        )
        return run is not None
    return False


def _rolling_windows(latest: date) -> list[tuple[date, date]]:
    return [
        (latest - timedelta(days=6), latest),
        (latest - timedelta(days=59), latest - timedelta(days=30)),
        (latest - timedelta(days=29), latest),
    ]
