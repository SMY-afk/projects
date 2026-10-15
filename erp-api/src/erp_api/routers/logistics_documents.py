from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from pydantic import BaseModel

from erp_api.core.permissions import (
    LOGISTICS_COST_RECONCILE,
    LOGISTICS_COST_VIEW,
    LOGISTICS_DISPATCH,
    LOGISTICS_VIEW,
    RETURNS_MANAGE,
    RETURNS_VIEW,
)
from erp_api.routers.auth import require_permissions, require_session
from erp_api.services.auth import AuthSession, CurrentUser
from erp_api.services.logistics_document_service import LogisticsDocumentService
from erp_api.services.logistics_shipping_errors import (
    LogisticsShippingNotFoundError,
    LogisticsShippingValidationError,
)

router = APIRouter()


class LogisticsDocumentResponse(BaseModel):
    id: UUID
    documentType: str
    ownerType: str
    ownerReferenceId: UUID
    originalFilename: str
    contentType: str
    sizeBytes: int
    sha256Hex: str
    isCurrent: bool
    createdByUserId: UUID
    createdAt: datetime
    downloadUrl: str
    expiresInSeconds: int


def _service(request: Request) -> LogisticsDocumentService:
    service = getattr(request.app.state, "logistics_document_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Object storage is not configured.",
        )
    return service


def _raise_error(error: ValueError) -> None:
    code = (
        status.HTTP_404_NOT_FOUND
        if isinstance(error, LogisticsShippingNotFoundError)
        else status.HTTP_422_UNPROCESSABLE_CONTENT
    )
    raise HTTPException(status_code=code, detail=str(error)) from error


async def _upload(
    document_type: str,
    owner_reference_id: UUID,
    file: UploadFile,
    session: AuthSession,
    user: CurrentUser,
    service: LogisticsDocumentService,
) -> LogisticsDocumentResponse:
    body = await file.read(service.max_bytes + 1)
    try:
        record = await service.upload(
            session.tenant_id,
            document_type=document_type,
            owner_reference_id=owner_reference_id,
            filename=file.filename or "document",
            content_type=file.content_type or "application/octet-stream",
            body=body,
            actor_user_id=user.id,
        )
    except (LogisticsShippingNotFoundError, LogisticsShippingValidationError) as error:
        _raise_error(error)
    return LogisticsDocumentResponse.model_validate(record)


async def _get(
    document_type: str,
    owner_reference_id: UUID,
    session: AuthSession,
    service: LogisticsDocumentService,
) -> LogisticsDocumentResponse:
    try:
        record = await service.get_current(
            session.tenant_id, document_type, owner_reference_id
        )
    except (LogisticsShippingNotFoundError, LogisticsShippingValidationError) as error:
        _raise_error(error)
    return LogisticsDocumentResponse.model_validate(record)


@router.post("/waybills/{waybill_id}/label", response_model=LogisticsDocumentResponse)
async def upload_waybill_label(
    waybill_id: UUID,
    file: UploadFile = File(...),
    session: AuthSession = Depends(require_session),
    user: CurrentUser = Depends(
        require_permissions(LOGISTICS_VIEW, LOGISTICS_DISPATCH)
    ),
    service: LogisticsDocumentService = Depends(_service),
) -> LogisticsDocumentResponse:
    return await _upload("shipping_label", waybill_id, file, session, user, service)


@router.get("/waybills/{waybill_id}/label", response_model=LogisticsDocumentResponse)
async def get_waybill_label(
    waybill_id: UUID,
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(LOGISTICS_VIEW, LOGISTICS_DISPATCH)),
    service: LogisticsDocumentService = Depends(_service),
) -> LogisticsDocumentResponse:
    return await _get("shipping_label", waybill_id, session, service)


@router.post(
    "/carrier-invoices/{reference_id}/document",
    response_model=LogisticsDocumentResponse,
)
async def upload_carrier_invoice(
    reference_id: UUID,
    file: UploadFile = File(...),
    session: AuthSession = Depends(require_session),
    user: CurrentUser = Depends(
        require_permissions(LOGISTICS_VIEW, LOGISTICS_COST_RECONCILE)
    ),
    service: LogisticsDocumentService = Depends(_service),
) -> LogisticsDocumentResponse:
    return await _upload("carrier_invoice", reference_id, file, session, user, service)


@router.get(
    "/carrier-invoices/{reference_id}/document",
    response_model=LogisticsDocumentResponse,
)
async def get_carrier_invoice(
    reference_id: UUID,
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(LOGISTICS_VIEW, LOGISTICS_COST_VIEW)),
    service: LogisticsDocumentService = Depends(_service),
) -> LogisticsDocumentResponse:
    return await _get("carrier_invoice", reference_id, session, service)


@router.post(
    "/return-proofs/{reference_id}/document", response_model=LogisticsDocumentResponse
)
async def upload_return_proof(
    reference_id: UUID,
    file: UploadFile = File(...),
    session: AuthSession = Depends(require_session),
    user: CurrentUser = Depends(require_permissions(RETURNS_VIEW, RETURNS_MANAGE)),
    service: LogisticsDocumentService = Depends(_service),
) -> LogisticsDocumentResponse:
    return await _upload("return_proof", reference_id, file, session, user, service)


@router.get(
    "/return-proofs/{reference_id}/document", response_model=LogisticsDocumentResponse
)
async def get_return_proof(
    reference_id: UUID,
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(RETURNS_VIEW)),
    service: LogisticsDocumentService = Depends(_service),
) -> LogisticsDocumentResponse:
    return await _get("return_proof", reference_id, session, service)
