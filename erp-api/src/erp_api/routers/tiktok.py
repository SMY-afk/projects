import json
import logging
from datetime import datetime
from uuid import UUID

from arq.connections import RedisSettings, create_pool
from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from pydantic import BaseModel

from erp_api.core.permissions import SHOP_MANAGE, SHOP_VIEW
from erp_api.routers.auth import require_permissions, require_session
from erp_api.services.auth import AuthSession, CurrentUser
from erp_api.services.shop_repository import ShopRepository
from erp_api.services.tiktok_apps import TikTokMultiAppAuthorizationService
from erp_api.services.tiktok_authorization import TikTokAuthorizationService
from erp_api.services.tiktok_client import TikTokClient
from erp_api.services.tiktok_reauthorization_repository import (
    TikTokReauthorizationRepository,
)
from erp_api.services.tiktok_transport import tiktok_request_context

router = APIRouter(prefix="/shops/tiktok", tags=["tiktok-shop"])
webhook_router = APIRouter(prefix="/webhooks", tags=["tiktok-shop"])
logger = logging.getLogger("erp_api.webhook")


class AuthorizationUrlResponse(BaseModel):
    authorizationUrl: str


class ConnectionStatusResponse(BaseModel):
    shopId: str
    platformShopId: str
    shopName: str
    status: str
    expiresAt: datetime | None
    scopes: list[str]


def _not_implemented() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="TikTok Shop integration is not configured yet.",
    )


def get_tiktok_authorization_service(
    request: Request,
) -> TikTokAuthorizationService | TikTokMultiAppAuthorizationService | None:
    return request.app.state.tiktok_authorization_service


def require_tiktok_authorization_service(
    request: Request,
) -> TikTokAuthorizationService | TikTokMultiAppAuthorizationService:
    service = get_tiktok_authorization_service(request)
    if not service:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    return service


def require_tiktok_client(request: Request) -> TikTokClient:
    client: TikTokClient | None = request.app.state.tiktok_client
    if not client:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    return client


def require_shop_repository(request: Request) -> ShopRepository:
    repository: ShopRepository | None = request.app.state.shop_repository
    if not repository:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    return repository


def require_tiktok_reauthorization_repository(
    request: Request,
) -> TikTokReauthorizationRepository:
    repository: TikTokReauthorizationRepository | None = getattr(
        request.app.state, "tiktok_reauthorization_repository", None
    )
    if not repository:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    return repository


@router.post("/authorization-url", response_model=AuthorizationUrlResponse)
async def create_authorization_url(
    app_profile: str = Query("legacy", alias="appProfile"),
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(SHOP_MANAGE)),
    authorization_service: TikTokAuthorizationService
    | TikTokMultiAppAuthorizationService = Depends(
        require_tiktok_authorization_service
    ),
) -> AuthorizationUrlResponse:
    try:
        authorization_url = await authorization_service.create_authorization_url(
            session.user_id,
            session.tenant_id,
            app_profile=app_profile,
        )
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
        ) from error
    return AuthorizationUrlResponse(authorizationUrl=authorization_url)


@router.get("/{shop_id}/connection", response_model=ConnectionStatusResponse)
async def get_connection_status(
    shop_id: UUID,
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(SHOP_VIEW)),
    repository: ShopRepository = Depends(require_shop_repository),
) -> ConnectionStatusResponse:
    connection_status = await repository.get_connection_status(
        session.tenant_id, shop_id
    )
    if not connection_status:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return ConnectionStatusResponse(**connection_status)


@router.post("/{shop_id}/refresh", response_model=ConnectionStatusResponse)
async def refresh_connection(
    shop_id: UUID,
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(SHOP_MANAGE)),
    client: TikTokClient = Depends(require_tiktok_client),
    repository: ShopRepository = Depends(require_shop_repository),
) -> ConnectionStatusResponse:
    refresh_token = await repository.get_refresh_token(session.tenant_id, shop_id)
    if not refresh_token:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT)
    with tiktok_request_context(tenant_id=str(session.tenant_id), shop_id=str(shop_id)):
        tokens = await client.refresh_access_token(refresh_token)
    if not await repository.update_connection_tokens(
        session.tenant_id, shop_id, tokens
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    connection_status = await repository.get_connection_status(
        session.tenant_id, shop_id
    )
    if not connection_status:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return ConnectionStatusResponse(**connection_status)


@router.post("/{shop_id}/disconnect", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect_connection(
    shop_id: UUID,
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(SHOP_MANAGE)),
    repository: ShopRepository = Depends(require_shop_repository),
) -> Response:
    if not await repository.disconnect(session.tenant_id, shop_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@webhook_router.post("/tiktok", status_code=status.HTTP_202_ACCEPTED)
async def webhook(
    request: Request,
    x_tts_signature: str | None = Header(None, alias="X-TTS-Signature"),
    x_tts_timestamp: str | None = Header(None, alias="X-TTS-Timestamp"),
) -> dict[str, object]:
    service = request.app.state.webhook_service
    if service is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    body = await request.body()
    try:
        service.verify(body, x_tts_signature or "", x_tts_timestamp or "")
        payload = json.loads(body)
        if not isinstance(payload, dict):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Webhook payload must be an object.",
            )
        event_id, created, tenant_id, shop_id = await service.store(payload, body)
    except json.JSONDecodeError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST) from error
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=str(error)
        ) from error
    except LookupError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from error
    queued = False
    if created:
        queue = None
        try:
            queue = await create_pool(
                RedisSettings.from_dsn(request.app.state.settings.redis_url)
            )
            queued = bool(
                await queue.enqueue_job(
                    "process_order_webhook_job",
                    str(tenant_id),
                    str(event_id),
                    _job_id=f"order-webhook:{event_id}",
                )
            )
        except Exception:
            logger.exception(
                "webhook_enqueue_failed",
                extra={
                    "event": "webhook_enqueue_failed",
                    "tenant_id": str(tenant_id),
                    "shop_id": str(shop_id),
                    "result": "failed",
                },
            )
            queued = False
        finally:
            if queue is not None:
                await queue.aclose()
    return {"eventId": str(event_id), "duplicate": not created, "queued": queued}
