from typing import Literal

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel

from erp_api.core.config import Settings, get_settings
from erp_api.infrastructure.health import probe_dependencies

router = APIRouter(tags=["health"])
api_router = APIRouter(prefix="/api", tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    dependencies: dict[str, str]


class ApiHealthResponse(BaseModel):
    status: Literal["ok"]
    service: str
    environment: str


@api_router.get("/health", response_model=ApiHealthResponse)
async def api_health(settings: Settings = Depends(get_settings)) -> ApiHealthResponse:
    return ApiHealthResponse(
        status="ok",
        service=settings.app_name,
        environment=settings.app_env,
    )


@router.get("/healthz", response_model=HealthResponse)
async def liveness() -> HealthResponse:
    return HealthResponse(status="ok", dependencies={})


@router.get("/readyz", response_model=HealthResponse)
async def readiness(
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings),
) -> HealthResponse:
    sample_config_status = _sample_sync_config_status(settings)
    dependencies = await probe_dependencies(
        request.app.state.database,
        settings.redis_url,
        sample_sync_enabled=sample_config_status == "ok",
    )
    dependencies["sample_sync_config"] = sample_config_status
    healthy = all(value in {"ok", "disabled"} for value in dependencies.values())
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(
        status="ok" if healthy else "degraded",
        dependencies=dependencies,
    )


def _sample_sync_config_status(settings: Settings) -> str:
    sample_target = (
        settings.feishu_sample_base_token,
        settings.feishu_sample_table_id,
    )
    if not any(sample_target):
        return "disabled"
    required = (
        settings.feishu_app_id,
        settings.feishu_app_secret,
        *sample_target,
        settings.tiktok_app_key,
        settings.tiktok_app_secret,
        settings.tiktok_token_url,
        settings.tiktok_shop_identity_url,
        settings.tiktok_token_encryption_key,
    )
    return "ok" if all(required) else "unavailable"
