from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from erp_api.core.permissions import LOGISTICS_VIEW, SYNC_TRIGGER
from erp_api.routers.auth import require_permissions, require_session
from erp_api.routers.logistics_alert_settings import router as settings_router
from erp_api.services.auth import AuthSession, CurrentUser
from erp_api.services.logistics_order_alerts import AlertPhase, OrderAlert
from erp_api.services.logistics_order_categories import OrderCategory
from erp_api.services.logistics_order_status_service import LogisticsOrderStatusService
from erp_api.services.tiktok_transport import TikTokApiError, TikTokClientError

router = APIRouter(prefix="/status", tags=["logistics-status"])
router.include_router(settings_router)


class PackageStatusResponse(BaseModel):
    packageId: str
    packageStatus: str
    carrierName: str | None
    trackingNumberMasked: str | None
    trackingStatus: str | None = None
    trackingCheckedAt: datetime | None = None


class OrderStatusResponse(BaseModel):
    id: UUID
    shopId: UUID
    shopName: str
    orderNumber: str
    orderCreatedAt: datetime
    platformStatus: str
    shippingType: str | None = None
    fulfillmentType: str | None = None
    platformUpdatedAt: datetime
    erpSyncedAt: datetime
    deliveredAt: datetime | None = None
    officialCheckedAt: datetime | None = None
    officialTrackingStatus: str | None = None
    packages: list[PackageStatusResponse]
    alerts: dict[OrderAlert, float] = Field(default_factory=dict)


class WarningCardResponse(BaseModel):
    key: OrderAlert
    thresholdHours: int
    upcomingCount: int
    overdueCount: int
    closestRemainingSeconds: float
    longestOverdueSeconds: float


class WarningsResponse(BaseModel):
    cards: list[WarningCardResponse]
    uniqueOrderCount: int
    upcomingUniqueOrderCount: int
    overdueUniqueOrderCount: int
    leadHours: float
    asOf: datetime
    lastDataSyncAt: datetime | None


class OrderStatusListResponse(BaseModel):
    items: list[OrderStatusResponse]
    total: int
    page: int
    pageSize: int
    categoryCounts: dict[str, int] = Field(default_factory=dict)
    syncResults: list[dict] = Field(default_factory=list)
    refreshFailedCount: int = 0
    warnings: WarningsResponse | None = None


class TrackingEventResponse(BaseModel):
    status: str
    occurredAt: datetime
    description: str | None
    actionCode: str


class LiveOrderStatusResponse(BaseModel):
    orderId: UUID
    trackingStatus: str | None
    checkedAt: datetime
    erpSyncedAt: datetime | None = None
    events: list[TrackingEventResponse]
    packages: list[PackageStatusResponse]
    platformStatus: str
    shippingType: str | None = None
    fulfillmentType: str | None = None
    platformUpdatedAt: datetime
    orderCreatedAt: datetime
    shippedAt: datetime | None
    firstLocationAt: datetime | None
    deliveredAt: datetime | None
    shippedDescription: str | None
    firstLocationDescription: str | None
    deliveredDescription: str | None
    milestoneNotes: list[str]


def _service(request: Request) -> LogisticsOrderStatusService:
    service = getattr(request.app.state, "logistics_order_status_service", None)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="TikTok logistics status is not configured.",
        )
    service.configure_realtime(
        request.app.state.order_sync_service, request.app.state.redis
    )
    return service


@router.post("/sync", response_model=OrderStatusListResponse)
async def sync_order_status_page(
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(LOGISTICS_VIEW, SYNC_TRIGGER)),
    service: LogisticsOrderStatusService = Depends(_service),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50, alias="pageSize"),
    shop_id: UUID | None = Query(None, alias="shopId"),
    order_number: str | None = Query(None, max_length=100, alias="orderNumber"),
    category: OrderCategory | None = Query(None),
    alert: OrderAlert | None = Query(None),
    alert_phase: AlertPhase = Query("overdue", alias="alertPhase"),
) -> OrderStatusListResponse:
    result = await service.sync_page(
        session.tenant_id,
        page=page,
        page_size=page_size,
        shop_id=shop_id,
        order_number=order_number.strip() or None if order_number else None,
        category=category,
        alert=alert,
        alert_phase=alert_phase,
    )
    return OrderStatusListResponse.model_validate(result)


@router.get("/orders", response_model=OrderStatusListResponse)
async def list_shipped_order_statuses(
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(LOGISTICS_VIEW)),
    service: LogisticsOrderStatusService = Depends(_service),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50, alias="pageSize"),
    shop_id: UUID | None = Query(None, alias="shopId"),
    order_number: str | None = Query(None, max_length=100, alias="orderNumber"),
    category: OrderCategory | None = Query(None),
    alert: OrderAlert | None = Query(None),
    alert_phase: AlertPhase = Query("overdue", alias="alertPhase"),
) -> OrderStatusListResponse:
    return OrderStatusListResponse.model_validate(
        await service.list_orders(
            session.tenant_id,
            page=page,
            page_size=page_size,
            shop_id=shop_id,
            order_number=order_number.strip() or None if order_number else None,
            category=category,
            alert=alert,
            alert_phase=alert_phase,
        )
    )


@router.get("/export-data", response_model=OrderStatusListResponse)
async def export_shipped_order_statuses(
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(LOGISTICS_VIEW)),
    service: LogisticsOrderStatusService = Depends(_service),
    shop_id: UUID | None = Query(None, alias="shopId"),
    order_number: str | None = Query(None, max_length=100, alias="orderNumber"),
    category: OrderCategory | None = Query(None),
    alert: OrderAlert | None = Query(None),
    alert_phase: AlertPhase = Query("overdue", alias="alertPhase"),
) -> OrderStatusListResponse:
    try:
        result = await service.export_orders(
            session.tenant_id,
            shop_id,
            order_number.strip() or None if order_number else None,
            category=category,
            alert=alert,
            alert_phase=alert_phase,
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return OrderStatusListResponse.model_validate(result)


@router.post("/orders/{order_id}/refresh", response_model=LiveOrderStatusResponse)
async def refresh_shipped_order_status(
    order_id: UUID,
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(LOGISTICS_VIEW)),
    service: LogisticsOrderStatusService = Depends(_service),
) -> LiveOrderStatusResponse:
    try:
        result = await service.refresh(session.tenant_id, order_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(
            status_code=502, detail="Official logistics response is invalid."
        ) from error
    except TikTokApiError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=f"TikTok logistics query failed ({error.code}).",
        ) from error
    except TikTokClientError as error:
        raise HTTPException(
            status_code=502, detail="TikTok logistics query is unavailable."
        ) from error
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return LiveOrderStatusResponse.model_validate(result)
