import logging
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field

from erp_api.core.permissions import LOGISTICS_DISPATCH, LOGISTICS_VIEW
from erp_api.routers.auth import require_permissions, require_session
from erp_api.routers.logistics_shipping_schemas import PackageResponse, WaybillResponse
from erp_api.services.auth import AuthSession, CurrentUser
from erp_api.services.logistics_dispatch_repository import LogisticsDispatchRepository
from erp_api.services.logistics_shipping_errors import (
    LogisticsShippingConflictError,
    LogisticsShippingNotFoundError,
    LogisticsShippingValidationError,
)
from erp_api.services.platform_fulfillment_outbox_repository import (
    PlatformFulfillmentOutboxRepository,
)
from erp_api.workers.platform_fulfillment_jobs import (
    enqueue_platform_fulfillment,
)

router = APIRouter()
logger = logging.getLogger("erp_api.logistics_dispatch")


class DispatchItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    taskItemId: UUID
    quantity: int = Field(ge=1)


class PackageDispatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    packageVersionId: int = Field(ge=1)
    waybillId: UUID
    waybillVersionId: int = Field(ge=1)
    items: Annotated[list[DispatchItemRequest], Field(min_length=1, max_length=500)]
    note: str | None = Field(None, max_length=2000)


class DispatchedItemResponse(BaseModel):
    taskItemId: UUID
    quantity: int


class PackageDispatchResponse(BaseModel):
    package: PackageResponse
    waybill: WaybillResponse
    taskId: UUID
    taskStatus: str
    taskVersionId: int
    shippedItems: list[DispatchedItemResponse]
    platformCallbackId: UUID | None = None
    platformCallbackQueued: bool = False


class PlatformFulfillmentCallbackResponse(BaseModel):
    id: UUID
    taskId: UUID
    packageId: UUID
    waybillId: UUID
    platform: str
    eventType: str
    status: str
    attemptCount: int
    nextAttemptAt: datetime | None
    lastErrorCode: str | None
    platformRequestId: str | None
    completedAt: datetime | None
    createdAt: datetime
    updatedAt: datetime


def _repository(request: Request) -> LogisticsDispatchRepository:
    repository = getattr(request.app.state, "logistics_dispatch_repository", None)
    if repository is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    return repository


def _outbox_repository(request: Request) -> PlatformFulfillmentOutboxRepository:
    repository = getattr(
        request.app.state, "platform_fulfillment_outbox_repository", None
    )
    if repository is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    return repository


@router.get(
    "/tasks/{task_id}/platform-fulfillment-callbacks",
    response_model=list[PlatformFulfillmentCallbackResponse],
)
async def list_platform_fulfillment_callbacks(
    task_id: UUID,
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(LOGISTICS_VIEW)),
    repository: PlatformFulfillmentOutboxRepository = Depends(_outbox_repository),
) -> list[PlatformFulfillmentCallbackResponse]:
    records = await repository.list_for_task(session.tenant_id, task_id)
    return [
        PlatformFulfillmentCallbackResponse.model_validate(record) for record in records
    ]


@router.post(
    "/packages/{package_id}/dispatch",
    response_model=PackageDispatchResponse,
)
async def dispatch_package(
    package_id: UUID,
    payload: PackageDispatchRequest,
    request: Request,
    session: AuthSession = Depends(require_session),
    user: CurrentUser = Depends(
        require_permissions(LOGISTICS_VIEW, LOGISTICS_DISPATCH)
    ),
    repository: LogisticsDispatchRepository = Depends(_repository),
) -> PackageDispatchResponse:
    try:
        record = await repository.dispatch(
            session.tenant_id,
            package_id,
            package_version_id=payload.packageVersionId,
            waybill_id=payload.waybillId,
            waybill_version_id=payload.waybillVersionId,
            actual_quantities=[
                (item.taskItemId, item.quantity) for item in payload.items
            ],
            actor_user_id=user.id,
            note=payload.note,
        )
    except LogisticsShippingNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(error)
        ) from error
    except LogisticsShippingConflictError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(error)
        ) from error
    except LogisticsShippingValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        ) from error
    callback_id = record.get("platformCallbackId")
    if isinstance(callback_id, UUID):
        try:
            record["platformCallbackQueued"] = await enqueue_platform_fulfillment(
                request.app.state.arq_queue,
                str(session.tenant_id),
                str(callback_id),
            )
        except Exception:
            record["platformCallbackQueued"] = False
            logger.exception(
                "platform_fulfillment_enqueue_failed",
                extra={
                    "event": "platform_fulfillment_enqueue_failed",
                    "tenant_id": str(session.tenant_id),
                    "outbox_id": str(callback_id),
                },
            )
    return PackageDispatchResponse.model_validate(record)
