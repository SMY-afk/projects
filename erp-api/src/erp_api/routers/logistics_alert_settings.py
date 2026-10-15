from fastapi import APIRouter, Depends

from erp_api.core.permissions import LOGISTICS_MANAGE, LOGISTICS_VIEW
from erp_api.routers.auth import require_permissions, require_session
from erp_api.services.auth import AuthSession, CurrentUser
from erp_api.services.logistics_alert_settings import (
    AlertSettings,
    LogisticsAlertSettings,
)

router = APIRouter()


@router.get("/alert-settings", response_model=AlertSettings)
async def read_alert_settings(
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(LOGISTICS_VIEW)),
):
    return LogisticsAlertSettings().read(session.tenant_id)


@router.put("/alert-settings", response_model=AlertSettings)
async def update_alert_settings(
    settings: AlertSettings,
    session: AuthSession = Depends(require_session),
    _: CurrentUser = Depends(require_permissions(LOGISTICS_VIEW, LOGISTICS_MANAGE)),
):
    return LogisticsAlertSettings().write(session.tenant_id, settings.leadHours, session.user_id)
