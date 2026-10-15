from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from erp_api.core.permissions import DASHBOARD_VIEW
from erp_api.routers.auth import require_permissions, require_session
from erp_api.routers.dashboard_ranking_schemas import DashboardAffiliateRankingsResponse
from erp_api.routers.dashboard_schemas import (
    DashboardPeriod,
    DashboardSelection,
    DashboardSnapshotResponse,
    RealtimeSection,
    TrendSection,
)
from erp_api.services.auth import AuthSession, CurrentUser
from erp_api.services.dashboard_affiliate_rankings import (
    DashboardAffiliateRankingsRepository,
)
from erp_api.services.dashboard_affiliate_repository import (
    DashboardAffiliateRepository,
)
from erp_api.services.dashboard_ranges import (
    OrderRange,
    RealtimeRange,
    TrendRange,
    order_window,
    realtime_windows,
    timezone_or_utc,
    trend_windows,
)
from erp_api.services.dashboard_repository import DashboardFilters, DashboardRepository

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/affiliate-rankings", response_model=DashboardAffiliateRankingsResponse)
async def get_dashboard_affiliate_rankings(
    request: Request,
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(DASHBOARD_VIEW)),
    platform: Annotated[str | None, Query(max_length=30)] = None,
    site: Annotated[str | None, Query(max_length=30)] = None,
    shop_id: Annotated[UUID | None, Query(alias="shopId")] = None,
    currency: Annotated[str, Query(min_length=3, max_length=3)] = "USD",
    days: Annotated[int, Query(ge=7, le=90)] = 30,
) -> DashboardAffiliateRankingsResponse:
    if days not in (7, 30, 90):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "days must be 7, 30, or 90"
        )
    filters = DashboardFilters(
        platform=platform.strip() if platform and platform.strip() else None,
        site=site.strip() if site and site.strip() else None,
        shop_id=shop_id,
        currency=currency.upper(),
    )
    repository = DashboardAffiliateRankingsRepository(
        request.app.state.database,
        request.app.state.affiliate_center_read_repository,
    )
    return DashboardAffiliateRankingsResponse.model_validate(
        await repository.snapshot(session.tenant_id, filters, days, datetime.now(UTC))
    )


@router.get("/snapshot", response_model=DashboardSnapshotResponse)
async def get_dashboard_snapshot(
    request: Request,
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(DASHBOARD_VIEW)),
    platform: Annotated[str | None, Query(max_length=30)] = None,
    site: Annotated[str | None, Query(max_length=30)] = None,
    shop_id: Annotated[UUID | None, Query(alias="shopId")] = None,
    currency: Annotated[str, Query(min_length=3, max_length=3)] = "USD",
    timezone_name: Annotated[
        str, Query(alias="timezone", min_length=1, max_length=64)
    ] = "UTC",
    realtime_range: Annotated[RealtimeRange, Query(alias="realtimeRange")] = "today",
    trend_range: Annotated[TrendRange, Query(alias="trendRange")] = "last7d",
    order_range: Annotated[OrderRange, Query(alias="orderRange")] = "last7d",
) -> DashboardSnapshotResponse:
    try:
        timezone = timezone_or_utc(timezone_name)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error)
        ) from error

    repository: DashboardRepository = request.app.state.dashboard_repository
    now = datetime.now(UTC)
    realtime = realtime_windows(realtime_range, timezone, now)
    trend = trend_windows(trend_range, timezone, now)
    orders = order_window(order_range, timezone, now)
    filters = DashboardFilters(
        platform=platform.strip() if platform and platform.strip() else None,
        site=site.strip() if site and site.strip() else None,
        shop_id=shop_id,
        currency=currency.upper(),
    )

    (
        options,
        realtime_current,
        realtime_previous,
        realtime_last_week,
        trend_current,
        trend_previous,
        trend_last_year,
        points,
        sales_distribution,
        order_distribution,
        fulfilment,
        products,
        affiliate_operations,
    ) = await asyncio.gather(
        repository.filter_options(session.tenant_id),
        repository.summary(session.tenant_id, filters, realtime.current),
        repository.summary(session.tenant_id, filters, realtime.previous),
        repository.summary(session.tenant_id, filters, realtime.last_year),
        repository.summary(session.tenant_id, filters, trend.current),
        repository.summary(session.tenant_id, filters, trend.previous),
        repository.summary(session.tenant_id, filters, trend.last_year),
        repository.trend(session.tenant_id, filters, trend.current, timezone_name),
        repository.sales_distribution(session.tenant_id, filters, trend.current),
        repository.order_distribution(session.tenant_id, filters, orders),
        repository.fulfilment(session.tenant_id, filters),
        repository.product_performance(session.tenant_id, filters, trend.current),
        DashboardAffiliateRepository(
            request.app.state.database,
            request.app.state.affiliate_center_read_repository,
        ).snapshot(session.tenant_id, filters, trend.current),
    )
    return DashboardSnapshotResponse(
        generatedAt=now,
        filters=options,
        selection=DashboardSelection(
            platform=filters.platform,
            site=filters.site,
            shopId=str(filters.shop_id) if filters.shop_id else None,
            currency=filters.currency,
            timezone=timezone_name,
            realtimeRange=realtime_range,
            trendRange=trend_range,
            orderRange=order_range,
        ),
        realtime=RealtimeSection(
            period=DashboardPeriod(
                start=realtime.current.start, end=realtime.current.end
            ),
            current=realtime_current,
            previous=realtime_previous,
            lastWeek=realtime_last_week,
        ),
        trend=TrendSection(
            period=DashboardPeriod(start=trend.current.start, end=trend.current.end),
            current=trend_current,
            previous=trend_previous,
            lastYear=trend_last_year,
            points=points,
        ),
        fulfilmentMetrics=fulfilment,
        salesDistribution=sales_distribution,
        orderDistribution=order_distribution,
        productPerformance=products,
        affiliateOperations=affiliate_operations,
    )
