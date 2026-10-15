from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from erp_api.core.permissions import LOGISTICS_MANAGE, LOGISTICS_VIEW
from erp_api.routers.auth import get_authenticated_user, require_session
from erp_api.routers.logistics_alert_settings import router
from erp_api.services.auth import AuthSession, CurrentUser
from erp_api.services.logistics_alert_settings import (
    AlertSettings,
    LogisticsAlertSettings,
)


def test_settings_survive_new_reader_and_are_isolated_by_tenant(tmp_path):
    tenant, other, actor = uuid4(), uuid4(), uuid4()
    settings = LogisticsAlertSettings(tmp_path)
    assert settings.read(tenant).leadHours == 3
    settings.write(tenant, 4.5, actor)
    assert LogisticsAlertSettings(tmp_path).read(tenant).leadHours == 4.5
    assert settings.read(other).leadHours == 3
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize("hours", [0, -1, 48, 100, float("nan"), float("inf")])
def test_invalid_lead_times_cannot_be_saved(hours):
    with pytest.raises(ValidationError):
        AlertSettings(leadHours=hours)


def test_settings_require_management_permission_and_reject_invalid_values(tmp_path, monkeypatch):
    monkeypatch.setenv("LOGISTICS_ALERT_SETTINGS_DIR", str(tmp_path))
    tenant, actor = uuid4(), uuid4()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_session] = lambda: AuthSession(actor, tenant)
    permissions = [LOGISTICS_VIEW]
    app.dependency_overrides[get_authenticated_user] = lambda: CurrentUser(actor, "User", "user", [], permissions)
    with TestClient(app) as client:
        assert client.get("/alert-settings").json()["leadHours"] == 3
        assert client.put("/alert-settings", json={"leadHours": 4}).status_code == 403
        permissions.append(LOGISTICS_MANAGE)
        assert client.put("/alert-settings", json={"leadHours": 48}).status_code == 422
        assert client.put("/alert-settings", json={"leadHours": 4}).json()["leadHours"] == 4
        assert client.get("/alert-settings").json()["leadHours"] == 4
