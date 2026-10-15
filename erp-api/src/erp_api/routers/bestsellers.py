from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from erp_api.core.permissions import BESTSELLERS_VIEW, SYNC_TRIGGER
from erp_api.routers.auth import require_permissions, require_session
from erp_api.routers.bestseller_schemas import (
    AuthorType,
    BestsellerAuthorizationStatus,
    BestsellerEntryResponse,
    BestsellerEnvelope,
    BestsellerFreshness,
    BestsellerGmvResponse,
    BestsellerListData,
    BestsellerQueryResponse,
    BestsellerReadError,
    BestsellerSyncRequest,
    BestsellerSyncResponse,
    Currency,
    EntityRoute,
    TimeSlot,
)
from erp_api.services.auth import AuthSession, CurrentUser
from erp_api.services.bestseller_read_repository import BestsellerReadRepository
from erp_api.services.bestseller_repository import BestsellerSnapshotQuery
from erp_api.services.shop_repository import ShopRepository
from erp_api.services.tiktok_scope_status import (
    BESTSELLER_REQUIRED_SCOPES,
    evaluate_scope_status,
)
from erp_api.workers.bestseller_jobs import bestseller_job_id

router = APIRouter(prefix="/bestsellers", tags=["bestsellers"])

ENTITY_TYPES = {
    "products": "product",
    "creators": "creator",
    "videos": "video",
    "lives": "live",
}
SAFE_ERROR_CATEGORIES = {
    "data_unavailable",
    "reauthorization_required",
    "not_authorized",
    "rate_limited",
    "timeout",
    "platform_error",
    "sync_failed",
}


def _shop_repository(request: Request) -> ShopRepository:
    repository = request.app.state.shop_repository
    if repository is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    return repository


def _read_repository(request: Request) -> BestsellerReadRepository:
    repository = request.app.state.bestseller_read_repository
    if repository is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    return repository


async def _connection(repository, tenant_id: UUID, shop_id: UUID):
    connection = await repository.get_connection_status(tenant_id, shop_id)
    if connection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return connection


@router.get(
    "/authorization-status",
    response_model=BestsellerEnvelope[BestsellerAuthorizationStatus],
)
async def authorization_status(
    shop_id: UUID = Query(..., alias="shopId"),
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(BESTSELLERS_VIEW)),
    repository: ShopRepository = Depends(_shop_repository),
) -> BestsellerEnvelope[BestsellerAuthorizationStatus]:
    connection = await _connection(repository, session.tenant_id, shop_id)
    scope_status = evaluate_scope_status(
        granted_scopes=connection["scopes"],
        required_scopes=BESTSELLER_REQUIRED_SCOPES,
    )
    authorized = connection["status"] == "authorized"
    ready = authorized and not scope_status.reauthorization_required
    state = (
        "ready"
        if ready
        else ("reauthorization_required" if authorized else "not_authorized")
    )
    return BestsellerEnvelope(
        source="local_connection",
        data=BestsellerAuthorizationStatus(
            shopId=shop_id,
            status=state,
            requiredScopes=list(scope_status.required_scopes),
            grantedScopes=list(scope_status.granted_scopes),
            missingScopes=list(scope_status.missing_scopes),
            canRead=ready,
        ),
        freshness=BestsellerFreshness(
            isStale=False,
            asOf=connection.get("updatedAt"),
        ),
        errors=[] if ready else [_read_error(state)],
    )


@router.post(
    "/sync",
    response_model=BestsellerEnvelope[BestsellerSyncResponse],
    status_code=status.HTTP_202_ACCEPTED,
)
async def sync_bestsellers(
    payload: BestsellerSyncRequest,
    request: Request,
    session: AuthSession = Depends(require_session),
    _view: CurrentUser = Depends(require_permissions(BESTSELLERS_VIEW)),
    _: CurrentUser = Depends(require_permissions(SYNC_TRIGGER)),
    repository: ShopRepository = Depends(_shop_repository),
) -> BestsellerEnvelope[BestsellerSyncResponse]:
    connection = await _connection(repository, session.tenant_id, payload.shopId)
    scopes = evaluate_scope_status(
        granted_scopes=connection["scopes"],
        required_scopes=BESTSELLER_REQUIRED_SCOPES,
    )
    if connection["status"] != "authorized" or scopes.reauthorization_required:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT)
    if request.app.state.bestseller_sync_service is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    _validate_completed_date(payload.date, connection, request)

    queued, existing = [], []
    for entity_route in dict.fromkeys(payload.entityTypes):
        entity_type = ENTITY_TYPES[entity_route]
        author_type = payload.authorType or "ALL" if entity_type == "creator" else None
        job_id = bestseller_job_id(
            session.tenant_id,
            payload.shopId,
            entity_type=entity_type,
            reference_date=payload.date,
            time_slot=payload.timeSlot,
            currency=payload.currency,
            author_type=author_type,
        )
        job = await request.app.state.arq_queue.enqueue_job(
            "sync_bestseller_job",
            str(session.tenant_id),
            str(payload.shopId),
            entity_type,
            payload.date.isoformat(),
            payload.timeSlot,
            payload.currency,
            author_type,
            _job_id=job_id,
        )
        (queued if job is not None else existing).append(job_id)
    return BestsellerEnvelope(
        source="queue",
        data=BestsellerSyncResponse(jobIds=queued, alreadyQueued=existing),
        freshness=BestsellerFreshness(isStale=False),
        errors=[],
    )


@router.get(
    "/{entity_type}",
    response_model=BestsellerEnvelope[BestsellerListData],
)
async def list_bestsellers(
    entity_type: EntityRoute,
    shop_id: UUID = Query(..., alias="shopId"),
    reference_date: date = Query(..., alias="date"),
    time_slot: TimeSlot = Query(..., alias="timeSlot"),
    currency: Currency = Query("USD"),
    author_type: AuthorType | None = Query(None, alias="authorType"),
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(BESTSELLERS_VIEW)),
    shop_repository: ShopRepository = Depends(_shop_repository),
    repository: BestsellerReadRepository = Depends(_read_repository),
) -> BestsellerEnvelope[BestsellerListData]:
    connection = await _connection(shop_repository, session.tenant_id, shop_id)
    normalized_entity = ENTITY_TYPES[entity_type]
    if normalized_entity != "creator" and author_type is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="authorType is only valid for creators.",
        )
    normalized_author = author_type or "ALL" if normalized_entity == "creator" else None
    query = BestsellerSnapshotQuery(
        shop_id=shop_id,
        entity_type=normalized_entity,
        reference_date=reference_date,
        time_slot=time_slot,
        currency=currency,
        author_type=normalized_author,
    )
    snapshot = await repository.get_snapshot(session.tenant_id, query)
    response_query = BestsellerQueryResponse(
        shopId=shop_id,
        market=connection.get("region"),
        date=reference_date,
        timeSlot=time_slot,
        currency=currency,
        authorType=normalized_author,
    )
    if snapshot is None:
        return BestsellerEnvelope(
            source="local_snapshot",
            data=BestsellerListData(query=response_query, items=[]),
            freshness=BestsellerFreshness(isStale=True),
            errors=[_read_error("data_unavailable")],
        )
    return BestsellerEnvelope(
        source="local_snapshot",
        data=BestsellerListData(
            query=response_query,
            items=[
                BestsellerEntryResponse(
                    entityType=normalized_entity,
                    externalId=entry.external_id,
                    rank=entry.rank,
                    displayName=entry.display_name,
                    gmv=BestsellerGmvResponse(
                        raw=entry.gmv_range_raw,
                        currencyContext=entry.gmv_currency_context,
                    ),
                    extensions=entry.extensions,
                )
                for entry in snapshot.entries
            ],
        ),
        freshness=BestsellerFreshness(
            isStale=snapshot.is_stale,
            asOf=snapshot.refreshed_at,
            lastErrorAt=snapshot.last_error_at,
        ),
        errors=(
            [_read_error(snapshot.last_error_category or "sync_failed")]
            if snapshot.is_stale
            else []
        ),
    )


def _read_error(category: str) -> BestsellerReadError:
    category = category if category in SAFE_ERROR_CATEGORIES else "sync_failed"
    reauthorize = category in {"reauthorization_required", "not_authorized"}
    if category == "data_unavailable":
        message = "No local snapshot is available for this query."
    elif category == "reauthorization_required":
        message = "TikTok Shop authorization must be renewed."
    elif category == "not_authorized":
        message = "The TikTok Shop connection is not authorized."
    else:
        message = "The last refresh failed; showing the last successful snapshot."
    return BestsellerReadError(
        code=category,
        message=message,
        action="reauthorize" if reauthorize else "resync",
    )


def _validate_completed_date(
    reference_date: date, connection, request: Request
) -> None:
    timezone = connection.get("timezone")
    if not isinstance(timezone, str) or not timezone:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Shop timezone is not configured.",
        )
    clock = getattr(request.app.state, "clock", None)
    now = clock() if callable(clock) else datetime.now(UTC)
    latest_completed = now.astimezone(ZoneInfo(timezone)).date() - timedelta(days=1)
    if reference_date > latest_completed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="date must be a completed shop-local calendar date.",
        )
