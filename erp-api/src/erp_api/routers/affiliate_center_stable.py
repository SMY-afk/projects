from datetime import date, datetime, timedelta
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from erp_api.core.permissions import AFFILIATE_CENTER_VIEW, SYNC_TRIGGER
from erp_api.routers.affiliate_center_schemas import AffiliateSyncRequest
from erp_api.routers.auth import require_permissions, require_session
from erp_api.services.affiliate_capture_health import (
    AffiliateCaptureHealthRepository,
)
from erp_api.services.affiliate_capture_intent_repository import (
    AffiliateCaptureIntentRepository,
)
from erp_api.services.affiliate_center_contract import (
    AffiliateCenterQuery,
    AffiliateCenterQueryError,
    AffiliateCenterResource,
)
from erp_api.services.affiliate_center_read_queries import (
    CreatorSort,
    VideoSort,
)
from erp_api.services.affiliate_center_read_repository import (
    AffiliateCenterReadRepository,
)
from erp_api.services.affiliate_daily_queries import split_daily_queries
from erp_api.services.affiliate_official_availability import (
    AffiliateOfficialAvailabilityRepository,
)
from erp_api.services.affiliate_official_enqueue import enqueue_official_queries
from erp_api.services.auth import AuthSession, CurrentUser

router = APIRouter(prefix="/affiliate-center", tags=["affiliate-center"])
Order = Literal["asc", "desc"]


def _repository(request: Request) -> AffiliateCenterReadRepository:
    return request.app.state.affiliate_center_read_repository


def _intent_repository(request: Request) -> AffiliateCaptureIntentRepository:
    return request.app.state.affiliate_capture_intent_repository


async def _source_kind(request: Request, tenant_id: UUID, shop_id: UUID) -> str:
    resolver = getattr(request.app.state, "affiliate_source_resolver", None)
    if resolver is None:
        return "page_capture"
    return await resolver.source_kind(tenant_id, shop_id)


async def _query(
    repository: AffiliateCenterReadRepository,
    tenant_id: UUID,
    resource: AffiliateCenterResource,
    shop_id: UUID,
    window_start: date,
    window_end: date,
    currency: str,
) -> AffiliateCenterQuery:
    shop = await repository.get_shop_context(tenant_id, shop_id)
    if shop is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Shop was not found.")
    timezone = shop.get("shopTimezone")
    if not isinstance(timezone, str) or not timezone:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Shop timezone is not configured.",
        )
    try:
        return AffiliateCenterQuery(
            resource=resource,
            shop_id=shop_id,
            window_start=window_start,
            window_end=window_end,
            shop_timezone=timezone,
            currency=currency,
            filters={},
        )
    except AffiliateCenterQueryError as error:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)
        ) from error


@router.get("/creators")
async def list_creators(
    shop_id: UUID = Query(..., alias="shopId"),
    window_start: date = Query(..., alias="from"),
    window_end: date = Query(..., alias="to"),
    currency: str = Query(..., min_length=3, max_length=3),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, alias="pageSize", ge=1, le=200),
    sort: CreatorSort = Query("affiliateGmvMinor"),
    order: Order = Query("desc"),
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(AFFILIATE_CENTER_VIEW)),
    repository: AffiliateCenterReadRepository = Depends(_repository),
) -> dict[str, object]:
    query = await _query(
        repository,
        session.tenant_id,
        AffiliateCenterResource.CREATORS,
        shop_id,
        window_start,
        window_end,
        currency,
    )
    return await repository.list_creators(
        session.tenant_id,
        query,
        page=page,
        page_size=page_size,
        sort=sort,
        order=order,
    )


@router.get("/videos")
async def list_videos(
    shop_id: UUID = Query(..., alias="shopId"),
    window_start: date = Query(..., alias="from"),
    window_end: date = Query(..., alias="to"),
    currency: str = Query(..., min_length=3, max_length=3),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, alias="pageSize", ge=1, le=200),
    sort: VideoSort = Query("gmvMinor"),
    order: Order = Query("desc"),
    creator_open_id: str | None = Query(
        None, alias="creatorOpenId", min_length=1, max_length=128
    ),
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(AFFILIATE_CENTER_VIEW)),
    repository: AffiliateCenterReadRepository = Depends(_repository),
) -> dict[str, object]:
    query = await _query(
        repository,
        session.tenant_id,
        AffiliateCenterResource.VIDEOS,
        shop_id,
        window_start,
        window_end,
        currency,
    )
    return await repository.list_videos(
        session.tenant_id,
        query,
        page=page,
        page_size=page_size,
        sort=sort,
        order=order,
        creator_open_id=creator_open_id,
    )


@router.get("/sync-status")
async def get_sync_status(
    request: Request,
    shop_id: UUID = Query(..., alias="shopId"),
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(AFFILIATE_CENTER_VIEW)),
    repository: AffiliateCenterReadRepository = Depends(_repository),
) -> dict[str, object]:
    if await repository.get_shop_context(session.tenant_id, shop_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Shop was not found.")
    source_kind = await _source_kind(request, session.tenant_id, shop_id)
    if source_kind == "official_api":
        shop = await repository.get_shop_context(session.tenant_id, shop_id)
        latest = await AffiliateOfficialAvailabilityRepository(
            request.app.state.arq_queue
        ).get(session.tenant_id, shop_id)
        if latest is None:
            timezone = str(shop["shopTimezone"])
            latest = datetime.now(ZoneInfo(timezone)).date() - timedelta(days=1)
        return {
            "items": await repository.sync_status(session.tenant_id, shop_id),
            "sourceKind": "official_api",
            "captureMode": "official_api_owned",
            "latestAvailableDates": {
                "creators": latest.isoformat(),
                "videos": latest.isoformat(),
            },
            "browser": None,
        }
    health = await AffiliateCaptureHealthRepository(request.app.state.arq_queue).get(
        session.tenant_id, shop_id
    )
    persisted_dates = await repository.latest_available_dates(
        session.tenant_id, shop_id
    )
    latest_dates = dict(persisted_dates)
    for resource in ("creators", "videos"):
        if observed_day := health.date_for(resource):
            latest_dates.setdefault(resource, observed_day)
    return {
        "items": await repository.sync_status(session.tenant_id, shop_id),
        "sourceKind": "page_capture",
        "captureMode": "browser_daemon_owned",
        "latestAvailableDates": {
            resource: value.isoformat() for resource, value in latest_dates.items()
        },
        "browser": health.as_dict(),
    }


@router.post("/sync", status_code=status.HTTP_202_ACCEPTED)
async def sync_affiliate_center(
    request: Request,
    payload: AffiliateSyncRequest,
    session: AuthSession = Depends(require_session),
    _view: CurrentUser = Depends(require_permissions(AFFILIATE_CENTER_VIEW)),
    _: CurrentUser = Depends(require_permissions(SYNC_TRIGGER)),
    repository: AffiliateCenterReadRepository = Depends(_repository),
    intent_repository: AffiliateCaptureIntentRepository = Depends(_intent_repository),
) -> dict[str, object]:
    queries = [
        await _query(
            repository,
            session.tenant_id,
            AffiliateCenterResource(resource),
            payload.shop_id,
            payload.window_start,
            payload.window_end,
            payload.currency,
        )
        for resource in payload.resources
    ]
    source_kind = await _source_kind(
        request, session.tenant_id, payload.shop_id
    )
    if source_kind == "official_api":
        latest = await AffiliateOfficialAvailabilityRepository(
            request.app.state.arq_queue
        ).get(session.tenant_id, payload.shop_id)
        if latest is not None and any(query.window_end > latest for query in queries):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"TikTok Affiliate data is available through {latest}.",
            )
        return await enqueue_official_queries(
            request.app.state.arq_queue,
            request.app.state.analytics_sync_repository,
            session.tenant_id,
            queries,
        )
    health = await AffiliateCaptureHealthRepository(request.app.state.arq_queue).get(
        session.tenant_id, payload.shop_id
    )
    persisted_dates = await repository.latest_available_dates(
        session.tenant_id, payload.shop_id
    )
    for query in queries:
        latest_available = health.date_for(
            query.resource.value
        ) or persisted_dates.get(query.resource.value)
        if latest_available is None:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                f"TikTok {query.resource.value} selectable date is unavailable; reconnect the shop browser listener.",
            )
        if query.window_end > latest_available:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"TikTok Affiliate data is available through {latest_available}.",
            )
    receipts = []
    for query in queries:
        receipts.extend(
            await intent_repository.enqueue(
                session.tenant_id,
                split_daily_queries(query),
                reuse_succeeded=True,
            )
        )
    return {
        "items": [
            {
                "runId": receipt.run_id,
                "resource": receipt.resource,
                "resourceType": receipt.resource_type,
                "status": receipt.status,
                "existing": receipt.existing,
            }
            for receipt in receipts
        ],
        "captureMode": "browser_daemon_owned",
    }
