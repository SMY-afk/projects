from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from erp_api.core.permissions import LOGISTICS_MANAGE, LOGISTICS_OPERATE, LOGISTICS_VIEW
from erp_api.routers.auth import require_permissions, require_session
from erp_api.routers.logistics_exception_schemas import (
    CloseRequest,
    DetectionRunResponse,
    EscalateRequest,
    ExceptionSeverity,
    ExceptionStatus,
    ExceptionType,
    LogisticsExceptionListResponse,
    LogisticsExceptionResponse,
    NoteRequest,
    PlatformLogisticsSyncResponse,
    ResolveRequest,
    VersionRequest,
)
from erp_api.services.auth import AuthSession, CurrentUser
from erp_api.services.logistics_exception_errors import (
    LogisticsExceptionConflictError,
    LogisticsExceptionNotFoundError,
    LogisticsExceptionValidationError,
)
from erp_api.services.logistics_exception_service import LogisticsExceptionService

router = APIRouter()


def _service(request: Request) -> LogisticsExceptionService:
    service = getattr(request.app.state, "logistics_exception_service", None)
    if service is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    return service


def _platform_sync_service(request: Request):
    service = getattr(request.app.state, "platform_logistics_sync_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="TikTok platform logistics sync is not configured.",
        )
    return service


def _raise_domain_error(error: ValueError) -> None:
    if isinstance(error, LogisticsExceptionNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(error)
        ) from error
    if isinstance(error, LogisticsExceptionConflictError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(error)
        ) from error
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
    ) from error


@router.get("/exceptions", response_model=LogisticsExceptionListResponse)
async def list_exceptions(
    session: AuthSession = Depends(require_session),
    user: CurrentUser = Depends(require_permissions(LOGISTICS_VIEW)),
    service: LogisticsExceptionService = Depends(_service),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100, alias="pageSize"),
    exception_type: ExceptionType | None = Query(None, alias="type"),
    exception_status: ExceptionStatus | None = Query(None, alias="status"),
    severity: ExceptionSeverity | None = Query(None),
    assigned_to_me: bool = Query(False, alias="assignedToMe"),
) -> LogisticsExceptionListResponse:
    result = await service.list_exceptions(
        session.tenant_id,
        page=page,
        page_size=page_size,
        exception_type=exception_type,
        status=exception_status,
        severity=severity,
        assigned_to_user_id=user.id if assigned_to_me else None,
    )
    return LogisticsExceptionListResponse(
        items=[
            LogisticsExceptionResponse.model_validate(item) for item in result.items
        ],
        total=result.total,
        page=page,
        pageSize=page_size,
    )


@router.post("/exceptions/detect", response_model=DetectionRunResponse)
async def detect_exceptions(
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(LOGISTICS_VIEW, LOGISTICS_MANAGE)),
    service: LogisticsExceptionService = Depends(_service),
) -> DetectionRunResponse:
    return DetectionRunResponse.model_validate(
        await service.scan_tenant(session.tenant_id)
    )


@router.post("/exceptions/sync-platform", response_model=PlatformLogisticsSyncResponse)
async def sync_platform_logistics(
    session: AuthSession = Depends(require_session),
    user: CurrentUser = Depends(require_permissions(LOGISTICS_VIEW, LOGISTICS_MANAGE)),
    service=Depends(_platform_sync_service),
    shop_id: UUID | None = Query(None, alias="shopId"),
) -> PlatformLogisticsSyncResponse:
    return PlatformLogisticsSyncResponse.model_validate(
        await service.sync_tenant(
            session.tenant_id,
            shop_id=shop_id,
            actor_user_id=user.id,
        )
    )


@router.get("/exceptions/{exception_id}", response_model=LogisticsExceptionResponse)
async def get_exception(
    exception_id: UUID,
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(LOGISTICS_VIEW)),
    service: LogisticsExceptionService = Depends(_service),
) -> LogisticsExceptionResponse:
    try:
        record = await service.get_exception(session.tenant_id, exception_id)
    except LogisticsExceptionNotFoundError as error:
        _raise_domain_error(error)
    return LogisticsExceptionResponse.model_validate(record)


@router.post(
    "/exceptions/{exception_id}/claim", response_model=LogisticsExceptionResponse
)
async def claim_exception(
    exception_id: UUID,
    payload: VersionRequest,
    session: AuthSession = Depends(require_session),
    user: CurrentUser = Depends(require_permissions(LOGISTICS_VIEW, LOGISTICS_OPERATE)),
    service: LogisticsExceptionService = Depends(_service),
) -> LogisticsExceptionResponse:
    return await _run_action(
        service.claim,
        session.tenant_id,
        exception_id,
        expected_version=payload.versionId,
        actor_user_id=user.id,
    )


@router.post(
    "/exceptions/{exception_id}/notes", response_model=LogisticsExceptionResponse
)
async def add_exception_note(
    exception_id: UUID,
    payload: NoteRequest,
    session: AuthSession = Depends(require_session),
    user: CurrentUser = Depends(require_permissions(LOGISTICS_VIEW, LOGISTICS_OPERATE)),
    service: LogisticsExceptionService = Depends(_service),
) -> LogisticsExceptionResponse:
    return await _run_action(
        service.add_note,
        session.tenant_id,
        exception_id,
        expected_version=payload.versionId,
        actor_user_id=user.id,
        note=payload.note,
    )


@router.post(
    "/exceptions/{exception_id}/escalate", response_model=LogisticsExceptionResponse
)
async def escalate_exception(
    exception_id: UUID,
    payload: EscalateRequest,
    session: AuthSession = Depends(require_session),
    user: CurrentUser = Depends(require_permissions(LOGISTICS_VIEW, LOGISTICS_MANAGE)),
    service: LogisticsExceptionService = Depends(_service),
) -> LogisticsExceptionResponse:
    return await _run_action(
        service.escalate,
        session.tenant_id,
        exception_id,
        expected_version=payload.versionId,
        actor_user_id=user.id,
        note=payload.note,
        severity=payload.severity,
    )


@router.post(
    "/exceptions/{exception_id}/resolve", response_model=LogisticsExceptionResponse
)
async def resolve_exception(
    exception_id: UUID,
    payload: ResolveRequest,
    session: AuthSession = Depends(require_session),
    user: CurrentUser = Depends(require_permissions(LOGISTICS_VIEW, LOGISTICS_OPERATE)),
    service: LogisticsExceptionService = Depends(_service),
) -> LogisticsExceptionResponse:
    return await _run_action(
        service.resolve,
        session.tenant_id,
        exception_id,
        expected_version=payload.versionId,
        actor_user_id=user.id,
        resolution=payload.resolution,
    )


@router.post(
    "/exceptions/{exception_id}/close", response_model=LogisticsExceptionResponse
)
async def close_exception(
    exception_id: UUID,
    payload: CloseRequest,
    session: AuthSession = Depends(require_session),
    user: CurrentUser = Depends(require_permissions(LOGISTICS_VIEW, LOGISTICS_MANAGE)),
    service: LogisticsExceptionService = Depends(_service),
) -> LogisticsExceptionResponse:
    return await _run_action(
        service.close,
        session.tenant_id,
        exception_id,
        expected_version=payload.versionId,
        actor_user_id=user.id,
        note=payload.note,
    )


async def _run_action(action, tenant_id: UUID, exception_id: UUID, **values):
    try:
        record = await action(tenant_id, exception_id, **values)
    except (
        LogisticsExceptionNotFoundError,
        LogisticsExceptionConflictError,
        LogisticsExceptionValidationError,
    ) as error:
        _raise_domain_error(error)
    return LogisticsExceptionResponse.model_validate(record)
