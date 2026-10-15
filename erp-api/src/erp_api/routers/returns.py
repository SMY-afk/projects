from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from erp_api.core.permissions import RETURNS_MANAGE, RETURNS_VIEW
from erp_api.routers.auth import require_permissions, require_session
from erp_api.routers.returns_schemas import (
    ReturnEligibilityResponse,
    ReturnRequestCreate,
    ReturnRequestListResponse,
    ReturnRequestResponse,
    ReturnReviewRequest,
    ReturnsModuleResponse,
    ReturnSyncRequest,
    ReturnSyncResponse,
)
from erp_api.services.auth import AuthSession, CurrentUser
from erp_api.services.returns_domain import (
    ReturnConflictError,
    ReturnItemInput,
    ReturnNotFoundError,
    ReturnValidationError,
)
from erp_api.services.returns_repository import ReturnsRepository
from erp_api.services.returns_sync_service import ReturnsSyncService

router = APIRouter(prefix="/returns", tags=["returns"])


def _repository(request: Request) -> ReturnsRepository:
    repository = getattr(request.app.state, "returns_repository", None)
    if repository is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    return repository


def _sync_service(request: Request) -> ReturnsSyncService:
    service = getattr(request.app.state, "returns_sync_service", None)
    if service is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    return service


def _raise_domain_error(error: ValueError) -> None:
    if isinstance(error, ReturnNotFoundError):
        code = status.HTTP_404_NOT_FOUND
    elif isinstance(error, ReturnConflictError):
        code = status.HTTP_409_CONFLICT
    else:
        code = status.HTTP_422_UNPROCESSABLE_CONTENT
    raise HTTPException(status_code=code, detail=str(error)) from error


@router.get("", response_model=ReturnsModuleResponse)
async def get_returns_module(
    _: CurrentUser = Depends(require_permissions(RETURNS_VIEW)),
) -> ReturnsModuleResponse:
    return ReturnsModuleResponse(module="returns", status="registered")


@router.get("/eligibility", response_model=ReturnEligibilityResponse)
async def get_return_eligibility(
    order_reference: str = Query(min_length=1, max_length=128, alias="orderReference"),
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(RETURNS_VIEW)),
    repository: ReturnsRepository = Depends(_repository),
) -> ReturnEligibilityResponse:
    try:
        record = await repository.get_eligibility(
            session.tenant_id, order_reference.strip()
        )
    except (ReturnNotFoundError, ReturnValidationError) as error:
        _raise_domain_error(error)
    return ReturnEligibilityResponse.model_validate(record)


@router.get("/requests", response_model=ReturnRequestListResponse)
async def list_return_requests(
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(RETURNS_VIEW)),
    repository: ReturnsRepository = Depends(_repository),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100, alias="pageSize"),
    request_status: Literal["pending_review", "approved", "rejected", "cancelled"]
    | None = Query(None, alias="status"),
    request_type: Literal["return", "exchange", "refund"] | None = Query(
        None, alias="requestType"
    ),
    shop_id: UUID | None = Query(None, alias="shopId"),
    reason: str | None = Query(None, min_length=1, max_length=128),
    applied_from: datetime | None = Query(None, alias="appliedFrom"),
    applied_to: datetime | None = Query(None, alias="appliedTo"),
    rma: str | None = Query(None, min_length=1, max_length=128),
) -> ReturnRequestListResponse:
    if applied_from and applied_to and applied_to < applied_from:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="appliedTo must not be earlier than appliedFrom.",
        )
    result = await repository.list_requests(
        session.tenant_id,
        page=page,
        page_size=page_size,
        status=request_status,
        request_type=request_type,
        shop_id=shop_id,
        reason=reason.strip() if reason else None,
        applied_from=applied_from,
        applied_to=applied_to,
        rma=rma.strip() if rma else None,
    )
    return ReturnRequestListResponse(
        items=[ReturnRequestResponse.model_validate(item) for item in result.items],
        total=result.total,
        page=page,
        pageSize=page_size,
    )


@router.post("/sync", response_model=ReturnSyncResponse)
async def sync_return_requests(
    payload: ReturnSyncRequest,
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(RETURNS_VIEW, RETURNS_MANAGE)),
    service: ReturnsSyncService = Depends(_sync_service),
) -> ReturnSyncResponse:
    try:
        result = await service.sync(session.tenant_id, shop_id=payload.shopId)
    except ReturnValidationError as error:
        _raise_domain_error(error)
    return ReturnSyncResponse.model_validate(result)


@router.post(
    "", response_model=ReturnRequestResponse, status_code=status.HTTP_201_CREATED
)
async def create_return_request(
    payload: ReturnRequestCreate,
    session: AuthSession = Depends(require_session),
    user: CurrentUser = Depends(require_permissions(RETURNS_VIEW, RETURNS_MANAGE)),
    repository: ReturnsRepository = Depends(_repository),
) -> ReturnRequestResponse:
    try:
        record = await repository.create_request(
            session.tenant_id,
            actor_user_id=user.id,
            order_id=payload.orderId,
            request_type=payload.requestType,
            reason_code=payload.reasonCode,
            customer_note=payload.customerNote,
            items=[
                ReturnItemInput(
                    order_line_id=item.orderLineId,
                    requested_quantity=item.requestedQuantity,
                    reason_code=item.reasonCode,
                    note=item.note,
                )
                for item in payload.items
            ],
        )
    except (ReturnNotFoundError, ReturnValidationError, ReturnConflictError) as error:
        _raise_domain_error(error)
    return ReturnRequestResponse.model_validate(record)


@router.get("/{request_id}", response_model=ReturnRequestResponse)
async def get_return_request(
    request_id: UUID,
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(RETURNS_VIEW)),
    repository: ReturnsRepository = Depends(_repository),
) -> ReturnRequestResponse:
    record = await repository.get_request(session.tenant_id, request_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return ReturnRequestResponse.model_validate(record)


@router.post("/{request_id}/review", response_model=ReturnRequestResponse)
async def review_return_request(
    request_id: UUID,
    payload: ReturnReviewRequest,
    session: AuthSession = Depends(require_session),
    user: CurrentUser = Depends(require_permissions(RETURNS_VIEW, RETURNS_MANAGE)),
    repository: ReturnsRepository = Depends(_repository),
) -> ReturnRequestResponse:
    try:
        record = await repository.review_request(
            session.tenant_id,
            actor_user_id=user.id,
            request_id=request_id,
            decision=payload.decision,
            version_id=payload.versionId,
            note=payload.note,
        )
    except (ReturnNotFoundError, ReturnValidationError, ReturnConflictError) as error:
        _raise_domain_error(error)
    return ReturnRequestResponse.model_validate(record)
