from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel

from erp_api.core.permissions import SHOP_VIEW
from erp_api.routers.auth import require_permissions, require_session
from erp_api.services.auth import AuthSession, CurrentUser
from erp_api.services.shop_repository import ShopRepository

router = APIRouter(prefix="/shops", tags=["shops"])


class ShopOption(BaseModel):
    id: UUID
    shopName: str
    platform: str
    platformShopId: str
    timezone: str | None


def _repository(request: Request) -> ShopRepository:
    repository: ShopRepository | None = request.app.state.shop_repository
    if repository is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    return repository


@router.get("", response_model=list[ShopOption])
async def list_shops(
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(SHOP_VIEW)),
    repository: ShopRepository = Depends(_repository),
) -> list[ShopOption]:
    return [
        ShopOption.model_validate(item)
        for item in await repository.list_shops(session.tenant_id)
    ]
