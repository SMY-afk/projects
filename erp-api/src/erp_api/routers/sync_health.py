from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel

from erp_api.core.permissions import DATA_VIEW
from erp_api.routers.auth import require_permissions, require_session
from erp_api.services.auth import AuthSession, CurrentUser
from erp_api.services.sync_health_repository import SyncHealthRepository

router = APIRouter(prefix="/sync-health", tags=["sync-health"])


class SyncHealthResponse(BaseModel):
    shopId: UUID
    shopName: str
    resourceType: str
    status: Literal["healthy", "degraded", "critical"]
    lastSuccessAt: datetime | None
    delaySeconds: int | None
    failureRate: float | None
    rateLimit429Count: int
    deadLetterCount: int
    dataGapCount: int
    totalRunCount: int
    successfulRunCount: int
    windowHours: int


def _repository(request: Request) -> SyncHealthRepository:
    return request.app.state.sync_health_repository


@router.get("", response_model=list[SyncHealthResponse])
async def list_sync_health(
    shop_id: UUID | None = Query(None, alias="shopId"),
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(DATA_VIEW)),
    repository: SyncHealthRepository = Depends(_repository),
) -> list[SyncHealthResponse]:
    rows = await repository.list_health(session.tenant_id, shop_id=shop_id)
    if shop_id is not None and not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Shop was not found.",
        )
    return [
        SyncHealthResponse(
            shopId=row.shop_id,
            shopName=row.shop_name,
            resourceType=row.resource_type,
            status=row.status,
            lastSuccessAt=row.last_success_at,
            delaySeconds=row.delay_seconds,
            failureRate=row.failure_rate,
            rateLimit429Count=row.rate_limit_429_count,
            deadLetterCount=row.dead_letter_count,
            dataGapCount=row.data_gap_count,
            totalRunCount=row.total_run_count,
            successfulRunCount=row.successful_run_count,
            windowHours=row.window_hours,
        )
        for row in rows
    ]
