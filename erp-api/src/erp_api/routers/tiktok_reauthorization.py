from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from erp_api.core.permissions import SHOP_MANAGE
from erp_api.routers.auth import require_permissions, require_session
from erp_api.routers.tiktok import (
    require_shop_repository,
    require_tiktok_authorization_service,
)
from erp_api.services.auth import AuthSession, CurrentUser
from erp_api.services.shop_repository import ShopRepository
from erp_api.services.tiktok_apps import TikTokMultiAppAuthorizationService
from erp_api.services.tiktok_authorization import TikTokAuthorizationService
from erp_api.services.tiktok_scope_status import (
    BESTSELLER_REQUIRED_SCOPES,
    TIKTOK_301_REQUIRED_SCOPES,
    evaluate_scope_status,
)

router = APIRouter(prefix="/shops/tiktok", tags=["tiktok-shop"])


class ReauthorizationUrlResponse(BaseModel):
    authorizationUrl: str


@router.post(
    "/{shop_id}/reauthorization-url",
    response_model=ReauthorizationUrlResponse,
)
async def create_reauthorization_url(
    shop_id: UUID,
    app_profile: str | None = Query(None, alias="appProfile"),
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(SHOP_MANAGE)),
    authorization_service: TikTokAuthorizationService
    | TikTokMultiAppAuthorizationService = Depends(
        require_tiktok_authorization_service
    ),
    repository: ShopRepository = Depends(require_shop_repository),
) -> ReauthorizationUrlResponse:
    connection = await repository.get_connection_status(session.tenant_id, shop_id)
    if connection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if connection["status"] != "authorized":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT)
    current_app_profile = str(connection.get("appProfile") or "legacy")
    target_app_profile = app_profile or current_app_profile
    required_scopes = (
        TIKTOK_301_REQUIRED_SCOPES
        if target_app_profile == "301"
        else BESTSELLER_REQUIRED_SCOPES
    )
    scope_status = evaluate_scope_status(
        granted_scopes=connection["scopes"],
        required_scopes=required_scopes,
    )
    if (
        target_app_profile == current_app_profile
        and not scope_status.reauthorization_required
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The TikTok shop already has all required scopes.",
        )
    try:
        authorization_url = await authorization_service.create_reauthorization_url(
            session.user_id,
            session.tenant_id,
            shop_id=shop_id,
            platform_shop_id=str(connection["platformShopId"]),
            required_scopes=scope_status.required_scopes,
            app_profile=target_app_profile,
        )
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
        ) from error
    return ReauthorizationUrlResponse(authorizationUrl=authorization_url)
