from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from erp_api.core.permissions import AFFILIATE_CENTER_VIEW
from erp_api.routers.auth import require_permissions, require_session
from erp_api.services.affiliate_center_contract import (
    AffiliateCenterQuery,
    AffiliateCenterQueryError,
    AffiliateCenterResource,
)
from erp_api.services.affiliate_center_read_repository import (
    AffiliateCenterReadRepository,
)
from erp_api.services.affiliate_creator_detail_read_repository import (
    AffiliateCreatorDetailReadRepository,
)
from erp_api.services.auth import AuthSession, CurrentUser

router = APIRouter(prefix="/affiliate-center/creators", tags=["affiliate-center"])
ResourceKind = Literal["video", "live", "product", "product-card"]


def _detail_repository(request: Request) -> AffiliateCreatorDetailReadRepository:
    return request.app.state.affiliate_creator_detail_read_repository


def _center_repository(request: Request) -> AffiliateCenterReadRepository:
    return request.app.state.affiliate_center_read_repository


async def _query(
    repository: AffiliateCenterReadRepository,
    tenant_id: UUID,
    shop_id: UUID,
    window_start: date,
    window_end: date,
    currency: str,
) -> AffiliateCenterQuery:
    shop = await repository.get_shop_context(tenant_id, shop_id)
    if shop is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Shop was not found.")
    timezone = shop.get("shopTimezone")
    if not isinstance(timezone, str):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Shop timezone is not configured.",
        )
    try:
        return AffiliateCenterQuery(
            resource=AffiliateCenterResource.CREATORS,
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


@router.get("/{creator_id}")
async def get_creator_detail(
    creator_id: UUID,
    shop_id: UUID = Query(..., alias="shopId"),
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(AFFILIATE_CENTER_VIEW)),
    repository: AffiliateCreatorDetailReadRepository = Depends(_detail_repository),
) -> dict[str, object]:
    creator = await repository.creator(session.tenant_id, shop_id, creator_id)
    if creator is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Creator was not found.")
    return {
        "creator": creator,
        "resources": await repository.statuses(session.tenant_id, shop_id, creator_id),
    }


@router.get("/{creator_id}/{resource}")
async def list_creator_detail_resource(
    creator_id: UUID,
    resource: ResourceKind,
    shop_id: UUID = Query(..., alias="shopId"),
    window_start: date = Query(..., alias="from"),
    window_end: date = Query(..., alias="to"),
    currency: str = Query(..., min_length=3, max_length=3),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, alias="pageSize", ge=1, le=200),
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(AFFILIATE_CENTER_VIEW)),
    center: AffiliateCenterReadRepository = Depends(_center_repository),
    repository: AffiliateCreatorDetailReadRepository = Depends(_detail_repository),
) -> dict[str, object]:
    query = await _query(
        center, session.tenant_id, shop_id, window_start, window_end, currency
    )
    kind = resource.replace("-", "_")
    return await repository.list_items(
        session.tenant_id,
        creator_id,
        query,
        kind,
        page=page,
        page_size=page_size,
    )
