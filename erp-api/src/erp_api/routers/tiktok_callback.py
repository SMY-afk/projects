from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel

from erp_api.routers.tiktok import (
    get_tiktok_authorization_service,
    require_shop_repository,
    require_tiktok_client,
    require_tiktok_reauthorization_repository,
)
from erp_api.services.creator_connection_repository import (
    CreatorAuthorizationError,
    CreatorConnectionRepository,
)
from erp_api.services.tiktok_reauthorization_repository import (
    TikTokConnectionTargetChanged,
)
from erp_api.services.tiktok_scope_status import evaluate_scope_status
from erp_api.services.tiktok_transport import tiktok_request_context

router = APIRouter(prefix="/shops/tiktok", tags=["tiktok-shop"])


class SellerAuthorizationCallbackResponse(BaseModel):
    shopId: str
    platformShopId: str
    status: str


class CreatorAuthorizationCallbackResponse(BaseModel):
    creatorConnectionId: str
    openId: str
    subjectType: Literal["creator"] = "creator"
    status: str


def _creator_repository(request: Request) -> CreatorConnectionRepository:
    repository: CreatorConnectionRepository | None = getattr(
        request.app.state, "creator_connection_repository", None
    )
    if not repository:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    return repository


@router.get("/callback")
async def authorization_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    app_key: str | None = None,
) -> SellerAuthorizationCallbackResponse | CreatorAuthorizationCallbackResponse:
    authorization_service = get_tiktok_authorization_service(request)
    if not authorization_service:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED)
    if not code:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)
    state_context = await authorization_service.consume_callback_state(
        state, app_key=app_key
    )
    if not state_context:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST)

    tenant_id = state_context.tenant_id
    client = require_tiktok_client(request)
    with tiktok_request_context(
        tenant_id=str(tenant_id),
        shop_id=str(state_context.shop_id) if state_context.shop_id else None,
        app_profile=state_context.app_profile,
    ):
        tokens = await client.exchange_code(code)
        if state_context.intent == "creator_authorize":
            try:
                connection = await _creator_repository(request).upsert_authorization(
                    tenant_id, state_context.user_id, tokens
                )
            except CreatorAuthorizationError as error:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT, detail=str(error)
                ) from error
            return CreatorAuthorizationCallbackResponse(
                creatorConnectionId=str(connection.id),
                openId=connection.open_id,
                status="authorized",
            )
        authorized_shops = await client.get_authorized_shops(tokens.access_token)

    repository = require_shop_repository(request)
    if state_context.intent == "scope_upgrade":
        scope_status = evaluate_scope_status(
            granted_scopes=tokens.scopes,
            required_scopes=state_context.required_scopes,
        )
        if scope_status.reauthorization_required:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="TikTok authorization did not grant all required scopes.",
            )
        authorized_shop = next(
            (
                shop
                for shop in authorized_shops
                if shop.platform_shop_id == state_context.platform_shop_id
            ),
            None,
        )
    else:
        authorized_shop = authorized_shops[0] if len(authorized_shops) == 1 else None
    if authorized_shop is None:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Authorized TikTok shop did not match the shop identity.",
        )

    if state_context.intent == "scope_upgrade":
        try:
            shop = await require_tiktok_reauthorization_repository(
                request
            ).replace_connection(
                tenant_id,
                state_context.shop_id,
                state_context.platform_shop_id,
                authorized_shop,
                tokens,
                app_profile=state_context.app_profile,
            )
        except TikTokConnectionTargetChanged as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The target TikTok shop connection changed.",
            ) from error
    else:
        shop = await repository.upsert_tiktok_shop(
            tenant_id,
            authorized_shop,
            tokens,
            app_profile=state_context.app_profile,
        )
    return SellerAuthorizationCallbackResponse(
        shopId=str(shop.id),
        platformShopId=authorized_shop.platform_shop_id,
        status="authorized",
    )
