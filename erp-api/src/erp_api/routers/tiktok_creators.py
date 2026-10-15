from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from erp_api.core.permissions import SHOP_MANAGE, SHOP_VIEW
from erp_api.routers.auth import require_permissions, require_session
from erp_api.services.auth import AuthSession, CurrentUser
from erp_api.services.creator_connection_repository import CreatorConnectionRepository
from erp_api.services.tiktok_authorization import TikTokAuthorizationService

router = APIRouter(prefix="/creators/tiktok", tags=["tiktok-creators"])


class CreatorAuthorizationUrlResponse(BaseModel):
    authorizationUrl: str


class CreatorConnectionResponse(BaseModel):
    id: str
    openId: str
    region: str | None
    status: str
    expiresAt: datetime | None
    scopes: list[str]


def require_authorization_service(request: Request) -> TikTokAuthorizationService:
    service: TikTokAuthorizationService | None = getattr(
        request.app.state, "tiktok_authorization_service", None
    )
    if not service:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    return service


def require_creator_repository(request: Request) -> CreatorConnectionRepository:
    repository: CreatorConnectionRepository | None = getattr(
        request.app.state, "creator_connection_repository", None
    )
    if not repository:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    return repository


@router.post("/authorization-url", response_model=CreatorAuthorizationUrlResponse)
async def create_creator_authorization_url(
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(SHOP_MANAGE)),
    authorization_service: TikTokAuthorizationService = Depends(
        require_authorization_service
    ),
) -> CreatorAuthorizationUrlResponse:
    try:
        authorization_url = (
            await authorization_service.create_creator_authorization_url(
                session.user_id, session.tenant_id
            )
        )
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(error),
        ) from error
    return CreatorAuthorizationUrlResponse(authorizationUrl=authorization_url)


@router.get("/connections", response_model=list[CreatorConnectionResponse])
async def list_creator_connections(
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(SHOP_VIEW)),
    repository: CreatorConnectionRepository = Depends(require_creator_repository),
) -> list[CreatorConnectionResponse]:
    connections = await repository.list_connections(session.tenant_id)
    return [CreatorConnectionResponse(**connection) for connection in connections]
