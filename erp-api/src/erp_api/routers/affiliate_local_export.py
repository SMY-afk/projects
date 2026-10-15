from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic_core import to_json

from erp_api.core.permissions import AFFILIATE_CENTER_VIEW
from erp_api.routers.auth import require_permissions, require_session
from erp_api.routers.local_read_access import require_local_read_export
from erp_api.services.affiliate_local_export_service import (
    AffiliateLocalExportError,
    build_affiliate_local_export,
)
from erp_api.services.auth import AuthSession, CurrentUser
from erp_api.services.feishu_creator_export_service import (
    FeishuCreatorExportError,
    build_feishu_creator_export,
)

router = APIRouter(prefix="/affiliate-center", tags=["affiliate-center"])
MAX_EXPORT_DAYS = 93


@router.get("/feishu-export")
async def export_feishu_creators(
    request: Request,
    _: AuthSession = Depends(require_session),
    __: CurrentUser = Depends(require_permissions(AFFILIATE_CENTER_VIEW)),
) -> Response:
    require_local_read_export(request)
    settings = request.app.state.settings
    app_id = getattr(settings, "feishu_new_app_id", None)
    app_secret = getattr(settings, "feishu_new_app_secret", None)
    if not app_id or not app_secret:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Feishu application credentials are not configured.",
        )
    try:
        payload = await build_feishu_creator_export(
            app_id,
            app_secret.get_secret_value(),
        )
    except FeishuCreatorExportError as error:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(error)) from error
    return Response(
        content=to_json(jsonable_encoder(payload)),
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="feishu-creators.json"'},
    )


@router.get("/local-export")
async def export_affiliate_center(
    request: Request,
    window_start: date = Query(..., alias="from"),
    window_end: date = Query(..., alias="to"),
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(AFFILIATE_CENTER_VIEW)),
) -> Response:
    require_local_read_export(request)
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
    now = _request_now(request)
    try:
        payload = await build_affiliate_local_export(
            session.tenant_id,
            window_start,
            window_end,
            now=now,
            shop_repository=request.app.state.affiliate_creator_repository,
            center_repository=request.app.state.affiliate_center_read_repository,
            live_repository=request.app.state.affiliate_live_account_repository,
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
    filename = (
        f"affiliate-center-{window_start.isoformat()}-to-{window_end.isoformat()}.json"
    )
    return Response(
        content=to_json(jsonable_encoder(payload)),
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _request_now(request: Request) -> datetime:
    clock = getattr(request.app.state, "clock", None)
    return clock() if callable(clock) else datetime.now(UTC)
