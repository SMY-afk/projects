from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from erp_api.core.permissions import DATA_VIEW, SYNC_TRIGGER
from erp_api.routers.auth import require_permissions, require_session
from erp_api.routers.data_presenters import (
    content_response,
    envelope,
    overview_snapshot,
    snapshot_response,
)
from erp_api.routers.data_schemas import (
    AdminResyncRequest,
    AdminResyncResponse,
    ContentRangeResponse,
    ContentResponse,
    Freshness,
    SnapshotResponse,
    SyncStatusResponse,
    V1Envelope,
    VideoContentEnvelope,
)
from erp_api.services.analytics_read_repository import AnalyticsReadRepository
from erp_api.services.analytics_repository import AnalyticsRepository
from erp_api.services.auth import AuthSession, CurrentUser
from erp_api.services.video_ranges import validate_video_window
from erp_api.workers.analytics_jobs import video_window_job_id

router = APIRouter(prefix="/data", tags=["data"])


def _snapshot_repository(request: Request) -> AnalyticsRepository:
    return request.app.state.analytics_repository


def _read_repository(request: Request) -> AnalyticsReadRepository:
    return request.app.state.analytics_read_repository


@router.get("/snapshots", response_model=V1Envelope[list[SnapshotResponse]])
@router.get("/trends", response_model=V1Envelope[list[SnapshotResponse]])
async def list_trends(
    shop_id: UUID = Query(..., alias="shopId"),
    metric_set: str = Query("trend", alias="metricSet", min_length=1, max_length=64),
    granularity: Literal["day", "hour"] = Query(...),
    from_: datetime = Query(..., alias="from"),
    to: datetime = Query(...),
    currency: str = Query(..., min_length=3, max_length=3),
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(DATA_VIEW)),
    repository: AnalyticsRepository = Depends(_snapshot_repository),
    read_repository: AnalyticsReadRepository = Depends(_read_repository),
) -> V1Envelope[list[SnapshotResponse]]:
    await _require_shop(read_repository, session.tenant_id, shop_id)
    rows = await repository.list_snapshots(
        session.tenant_id,
        shop_id,
        metric_set=metric_set,
        granularity=granularity,
        window_start=_utc(from_),
        window_end=_utc(to),
        currency=currency,
    )
    data = [
        snapshot_response(row, compose_metrics=metric_set == "trend") for row in rows
    ]
    return envelope("local_snapshot", data, [row.captured_at for row in rows])


@router.get("/overview", response_model=V1Envelope[list[SnapshotResponse]])
async def overview(
    shop_id: UUID = Query(..., alias="shopId"),
    from_: datetime = Query(..., alias="from"),
    to: datetime = Query(...),
    currency: str = Query(..., min_length=3, max_length=3),
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(DATA_VIEW)),
    repository: AnalyticsRepository = Depends(_snapshot_repository),
    read_repository: AnalyticsReadRepository = Depends(_read_repository),
) -> V1Envelope[list[SnapshotResponse]]:
    await _require_shop(read_repository, session.tenant_id, shop_id)
    rows = await repository.list_snapshots(
        session.tenant_id,
        shop_id,
        metric_set="trend",
        granularity="day",
        window_start=_utc(from_),
        window_end=_utc(to),
        currency=currency,
    )
    data = [overview_snapshot(rows)] if rows else []
    return envelope("local_snapshot", data, [row.captured_at for row in rows])


@router.get("/videos", response_model=VideoContentEnvelope)
async def list_content(
    request: Request,
    shop_id: UUID = Query(..., alias="shopId"),
    from_: datetime = Query(..., alias="from"),
    to: datetime = Query(...),
    currency: Literal["USD", "LOCAL"] = Query("USD"),
    account_type: Literal[
        "ALL",
        "OFFICIAL_ACCOUNTS",
        "MARKETING_ACCOUNTS",
        "AFFILIATE_ACCOUNTS",
    ] = Query("ALL", alias="accountType"),
    limit: int = Query(50, ge=1, le=100),
    sort_by: Literal["gmv", "gpm", "publishedAt"] = Query("gmv", alias="sortBy"),
    sort_order: Literal["asc", "desc"] = Query("desc", alias="sortOrder"),
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(DATA_VIEW)),
    repository: AnalyticsReadRepository = Depends(_read_repository),
) -> VideoContentEnvelope:
    await _require_shop(repository, session.tenant_id, shop_id)
    timezone = await repository.get_shop_timezone(session.tenant_id, shop_id)
    if not timezone:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Shop timezone is not configured.",
        )
    try:
        resolved = validate_video_window(
            window_start=from_,
            window_end=to,
            shop_timezone=timezone,
            now=_request_now(request),
        )
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error
    rows = await repository.list_content(
        session.tenant_id,
        shop_id,
        resource_type="video",
        limit=limit,
        sort_by=sort_by,
        sort_order=sort_order,
        window_start=resolved.window_start,
        window_end=resolved.window_end,
        currency=currency,
        account_type=account_type,
    )
    window_state = await repository.get_video_window_state(
        session.tenant_id,
        shop_id,
        window_start=resolved.window_start,
        window_end=resolved.window_end,
        currency=currency,
        account_type=account_type,
    )
    data = [content_response(row) for row in rows]
    base = (
        V1Envelope(
            source="local_detail",
            data=data,
            freshness=Freshness(isStale=False, asOf=window_state.finished_at),
        )
        if window_state is not None
        else envelope(
            "local_detail",
            data,
            [row.observed_at for row in rows],
            unavailable_message="No data is available for the requested time range.",
        )
    )
    return VideoContentEnvelope(
        **base.model_dump(),
        range=ContentRangeResponse(
            windowStart=resolved.window_start,
            windowEnd=resolved.window_end,
            shopTimezone=resolved.shop_timezone,
            isPartial=resolved.is_partial,
            latestAvailableDate=(
                window_state.latest_available_date if window_state is not None else None
            ),
        ),
    )


@router.get("/lives", response_model=V1Envelope[list[ContentResponse]])
async def list_lives(
    shop_id: UUID = Query(..., alias="shopId"),
    limit: int = Query(50, ge=1, le=100),
    sort_by: Literal["gmv", "startedAt"] = Query("gmv", alias="sortBy"),
    sort_order: Literal["asc", "desc"] = Query("desc", alias="sortOrder"),
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(DATA_VIEW)),
    repository: AnalyticsReadRepository = Depends(_read_repository),
) -> V1Envelope[list[ContentResponse]]:
    await _require_shop(repository, session.tenant_id, shop_id)
    rows = await repository.list_content(
        session.tenant_id,
        shop_id,
        resource_type="live",
        limit=limit,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return envelope(
        "local_detail",
        [content_response(row) for row in rows],
        [row.observed_at for row in rows],
    )


@router.get("/sync-status", response_model=V1Envelope[list[SyncStatusResponse]])
async def sync_status(
    shop_id: UUID = Query(..., alias="shopId"),
    limit: int = Query(20, ge=1, le=100),
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(DATA_VIEW)),
    repository: AnalyticsReadRepository = Depends(_read_repository),
) -> V1Envelope[list[SyncStatusResponse]]:
    await _require_shop(repository, session.tenant_id, shop_id)
    rows = await repository.list_sync_runs(session.tenant_id, shop_id, limit=limit)
    data = [
        SyncStatusResponse(
            runId=row.id,
            resourceType=row.resource_type,
            status=row.status,
            attemptCount=row.attempt_count,
            fetchedCount=row.fetched_count,
            persistedCount=row.persisted_count,
            errorCategory=row.error_category,
            errorSummary=row.error_summary,
            freshAt=row.fresh_at,
            startedAt=row.started_at,
            finishedAt=row.finished_at,
        )
        for row in rows
    ]
    return envelope(
        "local_sync", data, [row.fresh_at or row.started_at for row in rows]
    )


@router.post(
    "/resync",
    response_model=V1Envelope[AdminResyncResponse],
    status_code=status.HTTP_202_ACCEPTED,
)
async def resync_data(
    payload: AdminResyncRequest,
    request: Request,
    session: AuthSession = Depends(require_session),
    _data: CurrentUser = Depends(require_permissions(DATA_VIEW)),
    _: CurrentUser = Depends(require_permissions(SYNC_TRIGGER)),
    repository: AnalyticsReadRepository = Depends(_read_repository),
) -> V1Envelope[AdminResyncResponse]:
    await _require_shop(repository, session.tenant_id, payload.shop_id)
    if request.app.state.analytics_sync_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Analytics sync is not configured.",
        )
    resolved = None
    if payload.window_start is not None and payload.window_end is not None:
        timezone = await repository.get_shop_timezone(
            session.tenant_id, payload.shop_id
        )
        if not timezone:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Shop timezone is not configured.",
            )
        try:
            resolved = validate_video_window(
                window_start=_utc(payload.window_start),
                window_end=_utc(payload.window_end),
                shop_timezone=timezone,
                now=_request_now(request),
            )
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(error),
            ) from error
    queued, existing = [], []
    for resource_type in sorted(set(payload.resource_types)):
        job_id = (
            video_window_job_id(
                payload.shop_id,
                resolved.window_start,
                resolved.window_end,
                currency=payload.currency,
                account_type=payload.account_type,
                refresh_key=_request_now(request).strftime("%Y%m%d%H%M"),
            )
            if resolved is not None
            else f"analytics-sync:{payload.shop_id}:{resource_type}"
        )
        args = [
            "sync_analytics_job",
            str(session.tenant_id),
            str(payload.shop_id),
            resource_type,
        ]
        if resolved is not None:
            args.extend(
                [
                    resolved.window_start.isoformat(),
                    resolved.window_end.isoformat(),
                    payload.currency,
                    payload.account_type,
                ]
            )
        job = await request.app.state.arq_queue.enqueue_job(
            *args,
            source_kind="official_api",
            _job_id=job_id,
        )
        (queued if job is not None else existing).append(job_id)
    return V1Envelope(
        source="queue",
        data=AdminResyncResponse(jobIds=queued, alreadyQueued=existing),
        freshness=Freshness(isStale=False),
    )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Times must include a UTC offset.",
        )
    return value.astimezone(UTC)


def _request_now(request: Request) -> datetime:
    state = getattr(getattr(request, "app", None), "state", None)
    clock = getattr(state, "clock", None)
    return clock() if callable(clock) else datetime.now(UTC)


async def _require_shop(
    repository: AnalyticsReadRepository, tenant_id: UUID, shop_id: UUID
) -> None:
    if not await repository.shop_exists(tenant_id, shop_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Shop was not found."
        )
