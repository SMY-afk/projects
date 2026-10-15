from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from erp_api.core.permissions import AFFILIATE_CENTER_VIEW, SYNC_TRIGGER
from erp_api.routers.auth import require_permissions, require_session
from erp_api.routers.sample_application_schemas import (
    SampleSyncEnqueueResponse,
    SampleSyncMetricsResponse,
    SampleSyncPlanResponse,
    SampleSyncRequest,
    SampleSyncStatusResponse,
    SourceType,
    SyncType,
)
from erp_api.services.auth import AuthSession, CurrentUser
from erp_api.services.sample_sync_command import (
    SampleSyncCommandService,
    SampleSyncPlan,
)
from erp_api.services.sample_sync_metrics_repository import (
    SampleSyncMetrics,
    SampleSyncMetricsRepository,
)
from erp_api.services.sample_sync_status_repository import (
    SampleSyncStatus,
    SampleSyncStatusRepository,
)

router = APIRouter(prefix="/sample-applications", tags=["sample-applications"])


def _repository(request: Request) -> SampleSyncStatusRepository:
    database = request.app.state.database
    if database is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    return SampleSyncStatusRepository(database)


def _command_service(request: Request) -> SampleSyncCommandService:
    database = request.app.state.database
    if database is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    return SampleSyncCommandService(database)


def _metrics_repository(request: Request) -> SampleSyncMetricsRepository:
    database = request.app.state.database
    if database is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    return SampleSyncMetricsRepository(database)


@router.get("/metrics", response_model=list[SampleSyncMetricsResponse])
async def list_sample_sync_metrics(
    shop_id: UUID | None = Query(None, alias="shopId"),
    sync_type: SyncType | None = Query(None, alias="syncType"),
    source_type: SourceType | None = Query(None, alias="sourceType"),
    window_hours: int = Query(24, ge=1, le=2160, alias="windowHours"),
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(AFFILIATE_CENTER_VIEW)),
    status_repository: SampleSyncStatusRepository = Depends(_repository),
    metrics_repository: SampleSyncMetricsRepository = Depends(_metrics_repository),
) -> list[SampleSyncMetricsResponse]:
    if shop_id is not None and not await status_repository.shop_exists(
        session.tenant_id, shop_id
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Shop was not found.",
        )
    rows = await metrics_repository.list_metrics(
        session.tenant_id,
        shop_id=shop_id,
        sync_type=sync_type,
        source_type=source_type,
        window_hours=window_hours,
    )
    return [_to_metrics_response(row, window_hours) for row in rows]


@router.post("/sync/dry-run", response_model=SampleSyncPlanResponse)
async def dry_run_sample_sync(
    payload: SampleSyncRequest,
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(AFFILIATE_CENTER_VIEW)),
    service: SampleSyncCommandService = Depends(_command_service),
) -> SampleSyncPlanResponse:
    plan = await _require_plan(service, session.tenant_id, payload)
    return _to_plan_response(plan)


@router.post(
    "/sync",
    response_model=SampleSyncEnqueueResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def enqueue_sample_sync(
    payload: SampleSyncRequest,
    request: Request,
    session: AuthSession = Depends(require_session),
    _view: CurrentUser = Depends(require_permissions(AFFILIATE_CENTER_VIEW)),
    _: CurrentUser = Depends(require_permissions(SYNC_TRIGGER)),
    service: SampleSyncCommandService = Depends(_command_service),
) -> SampleSyncEnqueueResponse:
    plan = await _require_plan(service, session.tenant_id, payload)
    if not plan.ready:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": plan.reason_code},
        )
    try:
        job_id = await service.enqueue(request.app.state.arq_queue, plan)
    except RuntimeError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Sample sync queue is unavailable.",
        ) from error
    return SampleSyncEnqueueResponse(
        jobId=job_id,
        shopId=plan.shop_id,
        shopName=plan.shop_name,
        sourceType=plan.source_type,
        mode=plan.mode,
        status="queued",
    )


async def _require_plan(
    service: SampleSyncCommandService,
    tenant_id: UUID,
    payload: SampleSyncRequest,
) -> SampleSyncPlan:
    plan = await service.plan(
        tenant_id,
        payload.shopId,
        source_type=payload.sourceType,
        mode=payload.mode,
    )
    if plan is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Shop was not found.",
        )
    return plan


def _to_plan_response(plan: SampleSyncPlan) -> SampleSyncPlanResponse:
    return SampleSyncPlanResponse(
        shopId=plan.shop_id,
        shopName=plan.shop_name,
        sourceType=plan.source_type,
        mode=plan.mode,
        dryRun=True,
        ready=plan.ready,
        reasonCode=plan.reason_code,
    )


def _to_metrics_response(
    row: SampleSyncMetrics,
    window_hours: int,
) -> SampleSyncMetricsResponse:
    return SampleSyncMetricsResponse(
        shopId=row.shop_id,
        shopName=row.shop_name,
        syncType=row.sync_type,
        sourceType=row.source_type,
        windowHours=window_hours,
        runCount=row.run_count,
        queuedCount=row.queued_count,
        succeededCount=row.succeeded_count,
        partialCount=row.partial_count,
        failedCount=row.failed_count,
        runningCount=row.running_count,
        recordsRead=row.records_read,
        recordsCreated=row.records_created,
        recordsUpdated=row.records_updated,
        feishuCreated=row.feishu_created,
        feishuUpdated=row.feishu_updated,
        averageDurationSeconds=row.average_duration_seconds,
        lastSucceededAt=row.last_succeeded_at,
        lastFailedAt=row.last_failed_at,
    )


@router.get("/sync-status", response_model=list[SampleSyncStatusResponse])
async def list_sample_sync_status(
    shop_id: UUID | None = Query(None, alias="shopId"),
    sync_type: SyncType | None = Query(None, alias="syncType"),
    source_type: SourceType | None = Query(None, alias="sourceType"),
    limit: int = Query(20, ge=1, le=100),
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(AFFILIATE_CENTER_VIEW)),
    repository: SampleSyncStatusRepository = Depends(_repository),
) -> list[SampleSyncStatusResponse]:
    if shop_id is not None and not await repository.shop_exists(
        session.tenant_id, shop_id
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Shop was not found.",
        )
    rows = await repository.list_recent(
        session.tenant_id,
        shop_id=shop_id,
        sync_type=sync_type,
        source_type=source_type,
        limit=limit,
    )
    return [_to_response(row) for row in rows]


def _to_response(row: SampleSyncStatus) -> SampleSyncStatusResponse:
    duration_seconds = None
    if row.finished_at is not None:
        duration_seconds = max(
            0,
            int((row.finished_at - row.started_at).total_seconds()),
        )
    return SampleSyncStatusResponse(
        runId=row.run_id,
        shopId=row.shop_id,
        shopName=row.shop_name,
        syncType=row.sync_type,
        sourceType=row.source_type,
        status=row.status,
        pagesRead=row.pages_read,
        recordsRead=row.records_read,
        recordsCreated=row.records_created,
        recordsUpdated=row.records_updated,
        feishuCreated=row.feishu_created,
        feishuUpdated=row.feishu_updated,
        errorCode=row.error_code,
        startedAt=row.started_at,
        finishedAt=row.finished_at,
        durationSeconds=duration_seconds,
    )
