from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from secrets import compare_digest
from time import monotonic
from typing import Annotated
from uuid import UUID

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
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic_core import to_json

from erp_api.services.affiliate_local_export_service import (
    TARGET_SHOPS,
    AffiliateLocalExportError,
    build_affiliate_local_export,
)
from erp_api.services.feishu_creator_export_service import (
    FEISHU_MERGED_SOURCE,
    FeishuCreatorExportError,
    build_feishu_creator_export,
)

router = APIRouter(prefix="/internal/affiliate-center", tags=["internal-affiliate"])
MAX_EXPORT_DAYS = 93
CREATOR_EXPORT_CACHE_SECONDS = 30.0
LOCAL_EXPORT_CACHE_SECONDS = 30.0
_creator_export_lock = asyncio.Lock()
_creator_export_cache: tuple[float, tuple[object, ...], dict] | None = None
_local_export_cache: dict[tuple[object, ...], tuple[float, dict]] = {}
_local_export_locks: dict[tuple[object, ...], asyncio.Lock] = {}


def require_export_tenant(
    request: Request,
    service_token: Annotated[str | None, Header(alias="x-erp-service-token")] = None,
) -> UUID:
    settings = request.app.state.settings
    configured = getattr(settings, "affiliate_export_service_token", None)
    tenant_id = getattr(settings, "affiliate_export_tenant_id", None)
    if configured is None or tenant_id is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Affiliate export service access is not configured.",
        )
    expected = configured.get_secret_value()
    if not service_token or not compare_digest(service_token, expected):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": "ServiceToken"},
        )
    return tenant_id


@router.get("/feishu-export")
async def export_feishu_creators(
    request: Request,
    _: UUID = Depends(require_export_tenant),
) -> Response:
    settings = request.app.state.settings
    app_id = getattr(settings, "feishu_new_app_id", None)
    app_secret = getattr(settings, "feishu_new_app_secret", None)
    if not app_id or not app_secret:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Feishu application credentials are not configured.",
        )
    try:
        payload = await _cached_feishu_creator_export(
            app_id, app_secret.get_secret_value()
        )
    except FeishuCreatorExportError as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(error)) from error
    return _json_response(payload, "feishu-creators.json")


async def _cached_feishu_creator_export(
    app_id: str,
    app_secret: str,
) -> dict:
    """Coalesce concurrent prerequisite reads without hiding later source changes."""
    global _creator_export_cache
    cache_key = (app_id, FEISHU_MERGED_SOURCE)
    async with _creator_export_lock:
        now = monotonic()
        if (
            _creator_export_cache is not None
            and _creator_export_cache[0] > now
            and _creator_export_cache[1] == cache_key
        ):
            return _creator_export_cache[2]
        payload = await build_feishu_creator_export(app_id, app_secret)
        _creator_export_cache = (
            monotonic() + CREATOR_EXPORT_CACHE_SECONDS,
            cache_key,
            payload,
        )
        return payload


@router.get("/local-export")
async def export_affiliate_center(
    request: Request,
    window_start: date = Query(..., alias="from"),
    window_end: date = Query(..., alias="to"),
    shop: str | None = Query(None),
    tenant_id: UUID = Depends(require_export_tenant),
) -> Response:
    if window_end < window_start:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Export end date cannot be before start date.",
        )
    if (window_end - window_start).days + 1 > MAX_EXPORT_DAYS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"Local export is limited to {MAX_EXPORT_DAYS} days.",
        )
    targets = tuple(target for target in TARGET_SHOPS if target.business_name == shop)
    if shop is not None and not targets:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown shop.")
    try:
        payload = await _cached_affiliate_local_export(
            tenant_id,
            window_start,
            window_end,
            now=_request_now(request),
            shop_repository=request.app.state.affiliate_creator_repository,
            center_repository=request.app.state.affiliate_center_read_repository,
            live_repository=request.app.state.affiliate_live_account_repository,
            targets=targets if shop is not None else TARGET_SHOPS,
        )
    except AffiliateLocalExportError as error:
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content=jsonable_encoder(error.as_payload()),
        )
    except ValueError as error:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)
        ) from error
    filename = f"affiliate-center-{window_start}-to-{window_end}.json"
    return _json_response(payload, filename)


async def _cached_affiliate_local_export(
    tenant_id: UUID,
    window_start: date,
    window_end: date,
    *,
    now: datetime,
    shop_repository,
    center_repository,
    live_repository,
    targets: tuple[object, ...],
) -> dict:
    """Coalesce identical read-only exports requested by concurrent watchers."""
    key = (
        tenant_id,
        window_start,
        window_end,
        *(target.business_name for target in targets),
    )
    current = monotonic()
    for stale_key, (expires_at, _) in tuple(_local_export_cache.items()):
        if expires_at <= current:
            _local_export_cache.pop(stale_key, None)
            lock = _local_export_locks.get(stale_key)
            if lock is not None and not lock.locked():
                _local_export_locks.pop(stale_key, None)
    cached = _local_export_cache.get(key)
    if cached is not None and cached[0] > current:
        return cached[1]
    lock = _local_export_locks.setdefault(key, asyncio.Lock())
    async with lock:
        cached = _local_export_cache.get(key)
        if cached is not None and cached[0] > monotonic():
            return cached[1]
        payload = await build_affiliate_local_export(
            tenant_id,
            window_start,
            window_end,
            now=now,
            shop_repository=shop_repository,
            center_repository=center_repository,
            live_repository=live_repository,
            targets=targets,
        )
        _local_export_cache[key] = (
            monotonic() + LOCAL_EXPORT_CACHE_SECONDS,
            payload,
        )
        return payload


def _json_response(payload: object, filename: str) -> Response:
    return Response(
        content=to_json(jsonable_encoder(payload)),
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _request_now(request: Request) -> datetime:
    clock = getattr(request.app.state, "clock", None)
    return clock() if callable(clock) else datetime.now(UTC)
