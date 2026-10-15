from datetime import UTC, date, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, model_validator

from erp_api.core.permissions import AFFILIATE_CENTER_VIEW, SYNC_TRIGGER
from erp_api.routers.auth import require_permissions, require_session
from erp_api.routers.data_presenters import content_response, envelope
from erp_api.routers.data_schemas import ContentResponse, V1Envelope
from erp_api.services.affiliate_live_account_range import (
    AffiliateLiveRangePreset,
    resolve_live_range,
    split_live_range,
)
from erp_api.services.affiliate_live_account_repository import (
    AffiliateLiveAccountRepository,
)
from erp_api.services.auth import AuthSession, CurrentUser

router = APIRouter(prefix="/affiliate-center", tags=["affiliate-center"])


class AffiliateLiveSyncRequest(BaseModel):
    shop_id: UUID
    preset: AffiliateLiveRangePreset
    custom_from: date | None = None
    custom_to: date | None = None

    @model_validator(mode="before")
    @classmethod
    def accept_external_names(cls, value):
        if not isinstance(value, dict):
            return value
        normalized = dict(value)
        for external, internal in (
            ("shopId", "shop_id"),
            ("customFrom", "custom_from"),
            ("customTo", "custom_to"),
        ):
            if external in normalized and internal not in normalized:
                normalized[internal] = normalized[external]
        return normalized


class AffiliateLivePagination(BaseModel):
    page: int
    pageSize: int
    total: int


class AffiliateLiveAccountPageResponse(V1Envelope[list[ContentResponse]]):
    pagination: AffiliateLivePagination


def _repository(request: Request) -> AffiliateLiveAccountRepository:
    return request.app.state.affiliate_live_account_repository


async def _resolved_range(
    request: Request,
    repository: AffiliateLiveAccountRepository,
    tenant_id: UUID,
    shop_id: UUID,
    preset: AffiliateLiveRangePreset,
    custom_from: date | None = None,
    custom_to: date | None = None,
):
    if not await repository.shop_exists(tenant_id, shop_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Shop was not found.")
    timezone = await repository.get_shop_timezone(tenant_id, shop_id)
    if not timezone:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Shop timezone is not configured.",
        )
    try:
        return timezone, resolve_live_range(
            preset,
            timezone,
            _request_now(request),
            custom_from=custom_from,
            custom_to=custom_to,
        )
    except ValueError as error:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)
        ) from error


@router.get("/live-accounts", response_model=AffiliateLiveAccountPageResponse)
async def list_affiliate_live_accounts(
    request: Request,
    shop_id: UUID = Query(..., alias="shopId"),
    preset: AffiliateLiveRangePreset = Query("last7d"),
    custom_from: date | None = Query(None, alias="customFrom"),
    custom_to: date | None = Query(None, alias="customTo"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, alias="pageSize", ge=1, le=100),
    sort_by: Literal["gmv", "startedAt"] = Query("gmv", alias="sortBy"),
    sort_order: Literal["asc", "desc"] = Query("desc", alias="sortOrder"),
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(AFFILIATE_CENTER_VIEW)),
    repository: AffiliateLiveAccountRepository = Depends(_repository),
) -> AffiliateLiveAccountPageResponse:
    _, live_range = await _resolved_range(
        request,
        repository,
        session.tenant_id,
        shop_id,
        preset,
        custom_from,
        custom_to,
    )
    result = await repository.list_page(
        session.tenant_id,
        shop_id,
        page=page,
        page_size=page_size,
        sort_by=sort_by,
        sort_order=sort_order,
        account_type="AFFILIATE_ACCOUNTS",
        window_start=live_range.window_start,
        window_end=live_range.window_end,
    )
    response = envelope(
        "local_detail",
        [content_response(row) for row in result.items],
        [result.as_of],
    )
    return AffiliateLiveAccountPageResponse(
        **response.model_dump(),
        pagination=AffiliateLivePagination(
            page=page,
            pageSize=page_size,
            total=result.total,
        ),
    )


@router.post("/live-accounts/sync", status_code=status.HTTP_202_ACCEPTED)
async def sync_affiliate_live_accounts(
    request: Request,
    payload: AffiliateLiveSyncRequest,
    session: AuthSession = Depends(require_session),
    _view: CurrentUser = Depends(require_permissions(AFFILIATE_CENTER_VIEW)),
    _: CurrentUser = Depends(require_permissions(SYNC_TRIGGER)),
    repository: AffiliateLiveAccountRepository = Depends(_repository),
) -> dict[str, object]:
    timezone, live_range = await _resolved_range(
        request,
        repository,
        session.tenant_id,
        payload.shop_id,
        payload.preset,
        payload.custom_from,
        payload.custom_to,
    )
    request_slot = int(_request_now(request).timestamp()) // 300
    receipts = []
    for chunk in split_live_range(live_range, timezone, max_days=30):
        job_id = (
            f"analytics-sync:{payload.shop_id}:live-affiliate:"
            f"{chunk.window_start:%Y%m%d}:{chunk.window_end:%Y%m%d}:{request_slot}"
        )
        job = await request.app.state.arq_queue.enqueue_job(
            "sync_analytics_job",
            str(session.tenant_id),
            str(payload.shop_id),
            "live",
            window_start=chunk.window_start.isoformat(),
            window_end=chunk.window_end.isoformat(),
            currency="USD",
            account_type="AFFILIATE_ACCOUNTS",
            source_kind="official_api",
            _job_id=job_id,
        )
        receipts.append(
            {
                "jobId": job_id,
                "status": "queued",
                "existing": job is None,
            }
        )
    return {"items": receipts, "captureMode": "official_api_owned"}


def _request_now(request: Request) -> datetime:
    clock = getattr(request.app.state, "clock", None)
    return clock() if callable(clock) else datetime.now(UTC)
