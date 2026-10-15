from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from erp_api.core.errors import register_exception_handlers
from erp_api.core.permissions import MODULE_PERMISSION_CODES
from erp_api.routers.auth import get_authenticated_user, require_permissions
from erp_api.services.auth import CurrentUser


def _create_user(permissions: list[str]) -> CurrentUser:
    return CurrentUser(
        id=uuid4(),
        name="管理员",
        username="admin",
        roles=[],
        permissions=permissions,
    )


def _create_protected_client(
    required_permissions: list[str], granted_permissions: list[str]
) -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/resource")
    async def protected_resource(
        _: CurrentUser = Depends(require_permissions(*required_permissions)),
    ) -> dict[str, bool]:
        return {"ok": True}

    app.dependency_overrides[get_authenticated_user] = lambda: _create_user(
        granted_permissions
    )
    return TestClient(app)


@pytest.mark.parametrize("permission", sorted(MODULE_PERMISSION_CODES))
def test_module_permission_dependency_allows_the_exact_granted_permission(
    permission: str,
) -> None:
    with _create_protected_client([permission], [permission]) as client:
        response = client.get("/resource")

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_module_permission_dependency_rejects_a_missing_permission() -> None:
    with _create_protected_client(["shops:manage"], ["shops:view"]) as client:
        response = client.get("/resource")

    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


def test_module_permission_dependency_requires_every_permission() -> None:
    with _create_protected_client(
        ["shops:manage", "sync:trigger"], ["shops:manage"]
    ) as client:
        response = client.get("/resource")

    assert response.status_code == 403


def test_module_permission_dependency_rejects_unknown_permission_codes() -> None:
    with pytest.raises(ValueError, match="Unsupported permission"):
        require_permissions("unknown:permission")


def test_attribution_management_permission_is_not_enabled_in_read_only_phase() -> None:
    assert "orders:attribution:manage" not in MODULE_PERMISSION_CODES
    with pytest.raises(ValueError, match="Unsupported permission"):
        require_permissions("orders:attribution:manage")
