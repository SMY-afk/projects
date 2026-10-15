from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from erp_api.core.errors import register_exception_handlers
from erp_api.core.permissions import ORDERS_BUYER_PII_VIEW
from erp_api.main import create_app
from erp_api.routers import orders
from erp_api.routers.auth import get_authenticated_user, require_session
from erp_api.services.auth import AuthSession, CurrentUser


def _user(*permissions: str) -> CurrentUser:
    return CurrentUser(
        id=uuid4(),
        name="Administrator",
        username="admin",
        roles=[],
        permissions=list(permissions),
    )


def _client(router, *permissions: str) -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_authenticated_user] = lambda: _user(*permissions)
    return TestClient(app)


def test_only_logistics_and_returns_domain_routers_are_registered() -> None:
    paths = {route.path for route in create_app().routes}

    assert "/api/logistics" in paths
    assert "/api/returns" in paths
    assert "/api/warehouses" not in paths
    assert "/api/inventory" not in paths
    assert "/api/transfer-orders" not in paths


def test_logistics_router_requires_logistics_view_permission() -> None:
    from erp_api.routers import logistics

    with _client(logistics.router, "returns:view") as client:
        forbidden = client.get("/api/logistics")
    with _client(logistics.router, "logistics:view") as client:
        allowed = client.get("/api/logistics")

    assert forbidden.status_code == 403
    assert allowed.status_code == 200
    assert allowed.json() == {"module": "logistics", "status": "registered"}


def test_returns_router_requires_returns_view_permission() -> None:
    from erp_api.routers import returns

    with _client(returns.router, "logistics:view") as client:
        forbidden = client.get("/api/returns")
    with _client(returns.router, "returns:view") as client:
        allowed = client.get("/api/returns")

    assert forbidden.status_code == 403
    assert allowed.status_code == 200
    assert allowed.json() == {"module": "returns", "status": "registered"}


class RecipientRepository:
    def __init__(self) -> None:
        self.audit_results: list[str] = []

    async def get_order(self, tenant_id, order_id):
        return object()

    async def record_pii_access(self, tenant_id, **values) -> None:
        self.audit_results.append(values["result"])

    async def reveal_recipient(self, tenant_id, order_id):
        return {
            "name": "Full Name",
            "phone": "+1 555 0100",
            "address": "Full Address",
            "countryCode": "US",
            "purged": False,
        }


def _recipient_client(repository: RecipientRepository, *permissions: str) -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(orders.router, prefix="/api")
    app.dependency_overrides[require_session] = lambda: AuthSession(
        user_id=uuid4(), tenant_id=uuid4()
    )
    app.dependency_overrides[get_authenticated_user] = lambda: _user(*permissions)
    app.dependency_overrides[orders._repository] = lambda: repository
    return TestClient(app)


def test_logistics_permissions_do_not_grant_full_recipient_access() -> None:
    logistics_permissions = (
        "logistics:view",
        "logistics:operate",
        "logistics:dispatch",
        "logistics:manage",
        "returns:view",
        "returns:manage",
        "returns:inspect",
    )
    denied_repository = RecipientRepository()
    with _recipient_client(denied_repository, *logistics_permissions) as client:
        denied = client.get(f"/api/orders/{uuid4()}/recipient")

    allowed_repository = RecipientRepository()
    with _recipient_client(
        allowed_repository, *logistics_permissions, ORDERS_BUYER_PII_VIEW
    ) as client:
        allowed = client.get(f"/api/orders/{uuid4()}/recipient")

    assert denied.status_code == 403
    assert denied_repository.audit_results == ["denied"]
    assert allowed.status_code == 200
    assert allowed_repository.audit_results == ["granted"]
