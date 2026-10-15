from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel

from erp_api.core.permissions import LOGISTICS_VIEW
from erp_api.routers.auth import require_permissions, require_session
from erp_api.services.auth import AuthSession, CurrentUser
from erp_api.services.logistics_shipping_errors import (
    LogisticsShippingNotFoundError,
    LogisticsShippingValidationError,
)
from erp_api.services.logistics_tracking_repository import LogisticsTrackingRepository
from erp_api.services.logistics_tracking_service import (
    LogisticsTrackingService,
    TrackingWebhookAuthenticationError,
    TrackingWebhookPayloadError,
)

router = APIRouter()
webhook_router = APIRouter(prefix="/webhooks/logistics", tags=["logistics-webhooks"])


class TrackingEventResponse(BaseModel):
    id: UUID
    waybillId: UUID
    source: str
    externalEventId: str | None
    rawStatus: str
    status: str | None
    sequence: int | None
    occurredAt: datetime
    receivedAt: datetime
    location: str | None
    description: str | None
    accepted: bool
    ignoredReason: str | None


def _service(request: Request) -> LogisticsTrackingService:
    service = getattr(request.app.state, "logistics_tracking_service", None)
    if service is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    return service


def _repository(request: Request) -> LogisticsTrackingRepository:
    repository = getattr(request.app.state, "logistics_tracking_repository", None)
    if repository is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    return repository


@webhook_router.post(
    "/{tenant_id}/{carrier_code}", status_code=status.HTTP_202_ACCEPTED
)
async def receive_carrier_webhook(
    tenant_id: UUID,
    carrier_code: str,
    request: Request,
    signature: str | None = Header(None, alias="X-Carrier-Signature"),
    timestamp: str | None = Header(None, alias="X-Carrier-Timestamp"),
    service: LogisticsTrackingService = Depends(_service),
) -> dict[str, object]:
    try:
        result = await service.receive_webhook(
            tenant_id,
            carrier_code,
            await request.body(),
            signature=signature or "",
            timestamp=timestamp or "",
        )
    except LogisticsShippingNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(error)
        ) from error
    except LogisticsShippingValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        ) from error
    except RuntimeError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)
        ) from error
    except TrackingWebhookPayloadError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
        ) from error
    except TrackingWebhookAuthenticationError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(error)
        ) from error
    return {
        "received": result.received,
        "accepted": result.accepted,
        "duplicates": result.duplicates,
        "ignored": result.ignored,
        "eventIds": [str(item.event_id) for item in result.events],
    }


@router.get(
    "/waybills/{waybill_id}/tracking-events",
    response_model=list[TrackingEventResponse],
)
async def list_tracking_events(
    waybill_id: UUID,
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(LOGISTICS_VIEW)),
    repository: LogisticsTrackingRepository = Depends(_repository),
) -> list[TrackingEventResponse]:
    records = await repository.list_events(session.tenant_id, waybill_id)
    return [TrackingEventResponse.model_validate(item) for item in records]
