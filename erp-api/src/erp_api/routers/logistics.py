from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel

from erp_api.core.permissions import LOGISTICS_OPERATE, LOGISTICS_VIEW
from erp_api.routers.auth import require_permissions, require_session
from erp_api.routers.logistics_carrier_mapping import router as carrier_mapping_router
from erp_api.routers.logistics_dispatch import router as dispatch_router
from erp_api.routers.logistics_documents import router as documents_router
from erp_api.routers.logistics_exceptions import router as exceptions_router
from erp_api.routers.logistics_order_status import router as order_status_router
from erp_api.routers.logistics_packing import router as packing_router
from erp_api.routers.logistics_schemas import (
    LogisticsShopOptionResponse,
    LogisticsTaskCreateRequest,
    LogisticsTaskListResponse,
    LogisticsTaskResponse,
    LogisticsTasksGenerateRequest,
    LogisticsTasksGenerateResponse,
)
from erp_api.routers.logistics_shipping import router as shipping_router
from erp_api.routers.logistics_tracking import router as tracking_router
from erp_api.routers.logistics_workflow import router as workflow_router
from erp_api.services.auth import AuthSession, CurrentUser
from erp_api.services.logistics_repository import (
    LogisticsRepository,
    LogisticsSourceNotFoundError,
    LogisticsTaskConflictError,
    LogisticsTaskItemInput,
    LogisticsTaskValidationError,
)
from erp_api.services.logistics_task_generation_repository import (
    LogisticsTaskGenerationRepository,
    LogisticsTaskPlanInput,
    LogisticsTaskPlanItemInput,
)

router = APIRouter(prefix="/logistics", tags=["logistics"])
router.include_router(documents_router)
router.include_router(carrier_mapping_router)
router.include_router(exceptions_router)
router.include_router(order_status_router)
router.include_router(dispatch_router)
router.include_router(packing_router)
router.include_router(shipping_router)
router.include_router(tracking_router)
router.include_router(workflow_router)


class LogisticsModuleResponse(BaseModel):
    module: Literal["logistics"]
    status: Literal["registered"]


def _repository(request: Request) -> LogisticsRepository:
    repository = getattr(request.app.state, "logistics_repository", None)
    if repository is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    return repository


def _generation_repository(request: Request) -> LogisticsTaskGenerationRepository:
    repository = getattr(
        request.app.state, "logistics_task_generation_repository", None
    )
    if repository is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    return repository


def _raise_domain_error(error: ValueError) -> None:
    if isinstance(error, LogisticsSourceNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(error)
        ) from error
    if isinstance(error, LogisticsTaskConflictError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(error)
        ) from error
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
    ) from error


@router.get("", response_model=LogisticsModuleResponse)
async def get_logistics_module(
    _: CurrentUser = Depends(require_permissions(LOGISTICS_VIEW)),
) -> LogisticsModuleResponse:
    return LogisticsModuleResponse(module="logistics", status="registered")


@router.get("/shops", response_model=list[LogisticsShopOptionResponse])
async def list_logistics_shop_options(
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(LOGISTICS_VIEW)),
    repository: LogisticsRepository = Depends(_repository),
) -> list[LogisticsShopOptionResponse]:
    records = await repository.list_shop_options(session.tenant_id)
    return [LogisticsShopOptionResponse.model_validate(item) for item in records]


@router.get("/tasks", response_model=LogisticsTaskListResponse)
async def list_logistics_tasks(
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(LOGISTICS_VIEW)),
    repository: LogisticsRepository = Depends(_repository),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100, alias="pageSize"),
    task_status: Literal[
        "pending_review",
        "pending_pack",
        "pending_waybill",
        "pending_dispatch",
        "shipped",
        "in_transit",
        "delivered",
        "exception",
        "cancelled",
    ]
    | None = Query(None, alias="status"),
    source_type: Literal["sales_order", "return", "exchange"] | None = Query(
        None, alias="sourceType"
    ),
    shop_id: UUID | None = Query(None, alias="shopId"),
    priority: Literal["low", "normal", "high", "urgent"] | None = Query(None),
    created_from: datetime | None = Query(None, alias="createdFrom"),
    created_to: datetime | None = Query(None, alias="createdTo"),
) -> LogisticsTaskListResponse:
    result = await repository.list_tasks(
        session.tenant_id,
        page=page,
        page_size=page_size,
        status=task_status,
        source_type=source_type,
        shop_id=shop_id,
        priority=priority,
        created_from=created_from,
        created_to=created_to,
    )
    return LogisticsTaskListResponse(
        items=[LogisticsTaskResponse.model_validate(item) for item in result.items],
        total=result.total,
        page=page,
        pageSize=page_size,
    )


@router.post(
    "/tasks",
    response_model=LogisticsTaskResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_logistics_task(
    payload: LogisticsTaskCreateRequest,
    session: AuthSession = Depends(require_session),
    user: CurrentUser = Depends(require_permissions(LOGISTICS_VIEW, LOGISTICS_OPERATE)),
    repository: LogisticsRepository = Depends(_repository),
) -> LogisticsTaskResponse:
    try:
        task = await repository.create_sales_order_task(
            session.tenant_id,
            actor_user_id=user.id,
            order_id=payload.sourceId,
            items=[
                LogisticsTaskItemInput(
                    source_line_id=item.sourceLineId,
                    planned_quantity=item.plannedQuantity,
                )
                for item in payload.items
            ],
            priority=payload.priority,
            note=payload.note,
        )
    except (
        LogisticsSourceNotFoundError,
        LogisticsTaskValidationError,
        LogisticsTaskConflictError,
    ) as error:
        _raise_domain_error(error)
    return LogisticsTaskResponse.model_validate(task)


@router.post(
    "/tasks/generate",
    response_model=LogisticsTasksGenerateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def generate_logistics_tasks(
    payload: LogisticsTasksGenerateRequest,
    session: AuthSession = Depends(require_session),
    user: CurrentUser = Depends(require_permissions(LOGISTICS_VIEW, LOGISTICS_OPERATE)),
    repository: LogisticsTaskGenerationRepository = Depends(_generation_repository),
) -> LogisticsTasksGenerateResponse:
    try:
        records = await repository.generate_sales_order_tasks(
            session.tenant_id,
            actor_user_id=user.id,
            order_id=payload.orderId,
            plans=[
                LogisticsTaskPlanInput(
                    items=[
                        LogisticsTaskPlanItemInput(
                            order_line_id=item.orderLineId,
                            planned_quantity=item.plannedQuantity,
                        )
                        for item in plan.items
                    ],
                    priority=plan.priority,
                    note=plan.note,
                )
                for plan in payload.tasks
            ],
        )
    except (
        LogisticsSourceNotFoundError,
        LogisticsTaskValidationError,
        LogisticsTaskConflictError,
    ) as error:
        _raise_domain_error(error)
    return LogisticsTasksGenerateResponse(
        items=[LogisticsTaskResponse.model_validate(item) for item in records]
    )


@router.get("/tasks/{task_id}", response_model=LogisticsTaskResponse)
async def get_logistics_task(
    task_id: UUID,
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(LOGISTICS_VIEW)),
    repository: LogisticsRepository = Depends(_repository),
) -> LogisticsTaskResponse:
    task = await repository.get_task(session.tenant_id, task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return LogisticsTaskResponse.model_validate(task)
