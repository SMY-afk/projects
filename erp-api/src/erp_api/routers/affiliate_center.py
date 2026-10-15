from __future__ import annotations

from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
    status,
)

from erp_api.core.permissions import AFFILIATE_CENTER_VIEW
from erp_api.routers.auth import require_permissions, require_session
from erp_api.services.affiliate_center_capture_policy import (
    affiliate_center_capture_policy_contract,
)
from erp_api.services.affiliate_center_contract import (
    AffiliateCenterResource,
)
from erp_api.services.affiliate_center_display_contract import (
    affiliate_center_display_contract,
)
from erp_api.services.affiliate_creator_repository import AffiliateCreatorRepository
from erp_api.services.auth import AuthSession, CurrentUser

router = APIRouter(prefix="/affiliate-center", tags=["affiliate-center"])
QUERY_DIMENSIONS = [
    "shopId",
    "windowStart",
    "windowEnd",
    "shopTimezone",
    "currency",
    "filters",
]


def _repository(request: Request) -> AffiliateCreatorRepository:
    return request.app.state.affiliate_creator_repository


@router.get("/resources")
async def list_resources(
    _: CurrentUser = Depends(require_permissions(AFFILIATE_CENTER_VIEW)),
) -> dict[str, object]:
    return {
        "items": [
            {"key": AffiliateCenterResource.CREATORS.value, "label": "达人"},
            {"key": AffiliateCenterResource.VIDEOS.value, "label": "所有视频"},
        ],
        "queryDimensions": QUERY_DIMENSIONS,
        "windowSemantics": "inclusive_shop_local_dates",
        "display": affiliate_center_display_contract(),
        "capturePolicy": affiliate_center_capture_policy_contract(),
    }


@router.get("/shops")
async def list_shops(
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(AFFILIATE_CENTER_VIEW)),
    repository: AffiliateCreatorRepository = Depends(_repository),
) -> dict[str, object]:
    return {"items": await repository.list_shops(session.tenant_id)}


@router.get("/reports")
async def list_reports(
    shopId: UUID = Query(...),
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(AFFILIATE_CENTER_VIEW)),
    repository: AffiliateCreatorRepository = Depends(_repository),
) -> dict[str, object]:
    return {"items": await repository.list_reports(session.tenant_id, shopId)}


@router.get("/reports/{report_id}/creators")
async def list_report_creators(
    report_id: UUID,
    shopId: UUID = Query(...),
    page: int = Query(1, ge=1),
    pageSize: int = Query(50, ge=1, le=200),
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(AFFILIATE_CENTER_VIEW)),
    repository: AffiliateCreatorRepository = Depends(_repository),
) -> dict[str, object]:
    result = await repository.list_metrics(
        session.tenant_id,
        shopId,
        report_id,
        page=page,
        page_size=pageSize,
    )
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "联盟达人报表不存在。")
    return result
