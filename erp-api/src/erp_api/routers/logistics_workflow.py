from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from erp_api.core.permissions import LOGISTICS_OPERATE, LOGISTICS_VIEW
from erp_api.routers.auth import require_permissions, require_session
from erp_api.routers.logistics_schemas import (
    LogisticsOrderContextResponse,
    LogisticsPickingCompletionRequest,
    LogisticsScanResolveRequest,
    LogisticsScanResolveResponse,
    LogisticsTaskResponse,
    LogisticsTaskReviewRequest,
)
from erp_api.services.auth import AuthSession, CurrentUser
from erp_api.services.logistics_repository import (
    LogisticsRepository,
    LogisticsTaskConflictError,
    LogisticsTaskValidationError,
)
from erp_api.services.logistics_workflow_repository import (
    LogisticsWorkflowRepository,
    ReviewItemInput,
)

router = APIRouter()


def _task_repository(request: Request) -> LogisticsRepository:
    repository = getattr(request.app.state, "logistics_repository", None)
    if repository is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    return repository


def _workflow_repository(request: Request) -> LogisticsWorkflowRepository:
    repository = getattr(request.app.state, "logistics_workflow_repository", None)
    if repository is not None:
        return repository
    database = getattr(request.app.state, "database", None)
    if database is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    return LogisticsWorkflowRepository(database)


def _raise_domain_error(error: ValueError) -> None:
    code = (
        status.HTTP_409_CONFLICT
        if isinstance(error, LogisticsTaskConflictError)
        else status.HTTP_422_UNPROCESSABLE_CONTENT
    )
    raise HTTPException(status_code=code, detail=str(error)) from error


@router.get(
    "/tasks/{task_id}/order-context",
    response_model=LogisticsOrderContextResponse,
)
async def get_logistics_order_context(
    task_id: UUID,
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(LOGISTICS_VIEW)),
    repository: LogisticsRepository = Depends(_task_repository),
) -> LogisticsOrderContextResponse:
    record = await repository.get_order_context(session.tenant_id, task_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return LogisticsOrderContextResponse.model_validate(record)


@router.post(
    "/tasks/{task_id}/picking-completion", response_model=LogisticsTaskResponse
)
async def confirm_picking_completion(
    task_id: UUID,
    payload: LogisticsPickingCompletionRequest,
    session: AuthSession = Depends(require_session),
    user: CurrentUser = Depends(require_permissions(LOGISTICS_VIEW, LOGISTICS_OPERATE)),
    repository: LogisticsWorkflowRepository = Depends(_workflow_repository),
) -> LogisticsTaskResponse:
    try:
        task = await repository.confirm_picking_completed(
            session.tenant_id,
            task_id,
            actor_user_id=user.id,
            note=payload.note,
        )
    except LogisticsTaskConflictError as error:
        _raise_domain_error(error)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return LogisticsTaskResponse.model_validate(task)


@router.post("/scans/resolve", response_model=LogisticsScanResolveResponse)
async def resolve_logistics_scan(
    payload: LogisticsScanResolveRequest,
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(LOGISTICS_VIEW, LOGISTICS_OPERATE)),
    repository: LogisticsWorkflowRepository = Depends(_workflow_repository),
) -> LogisticsScanResolveResponse:
    record = await repository.resolve_scan(
        session.tenant_id,
        code=payload.code,
        task_id=payload.taskId,
    )
    return LogisticsScanResolveResponse.model_validate(record)


@router.post("/tasks/{task_id}/reviews", response_model=LogisticsTaskResponse)
async def review_logistics_task(
    task_id: UUID,
    payload: LogisticsTaskReviewRequest,
    session: AuthSession = Depends(require_session),
    user: CurrentUser = Depends(require_permissions(LOGISTICS_VIEW, LOGISTICS_OPERATE)),
    repository: LogisticsWorkflowRepository = Depends(_workflow_repository),
) -> LogisticsTaskResponse:
    try:
        task = await repository.record_review(
            session.tenant_id,
            task_id,
            actor_user_id=user.id,
            items=[
                ReviewItemInput(
                    task_item_id=item.taskItemId,
                    actual_quantity=item.actualQuantity,
                    difference_reason=item.differenceReason,
                )
                for item in payload.items
            ],
            note=payload.note,
        )
    except (LogisticsTaskValidationError, LogisticsTaskConflictError) as error:
        _raise_domain_error(error)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return LogisticsTaskResponse.model_validate(task)
