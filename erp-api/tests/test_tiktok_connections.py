from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from erp_api.main import app
from erp_api.services.auth import AuthAccount, AuthService, CurrentUser, hash_password
from erp_api.services.tiktok_authorization import TikTokAuthorizationService
from erp_api.services.tiktok_client import TikTokTokenSet
from erp_api.services.tiktok_transport import get_tiktok_request_context


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def set(self, key: str, value: str, *, ex: int) -> None:
        del ex
        self.values[key] = value

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def getdel(self, key: str) -> str | None:
        return self.values.pop(key, None)

    async def delete(self, key: str) -> int:
        return int(self.values.pop(key, None) is not None)

    async def incr(self, key: str) -> int:
        value = int(self.values.get(key, "0")) + 1
        self.values[key] = str(value)
        return value

    async def expire(self, key: str, seconds: int) -> bool:
        del key, seconds
        return True


@dataclass(frozen=True)
class FakeAuthRepository:
    account: AuthAccount
    user: CurrentUser

    async def find_account_by_username(self, username: str) -> AuthAccount | None:
        return self.account if username == self.account.username else None

    async def get_current_user(
        self, user_id: UUID, tenant_id: UUID
    ) -> CurrentUser | None:
        return (
            self.user
            if user_id == self.account.id and tenant_id == self.account.tenant_id
            else None
        )


class FakeTikTokClient:
    def __init__(self) -> None:
        self.refresh_tokens: list[str] = []

    async def refresh_access_token(self, refresh_token: str) -> TikTokTokenSet:
        self.refresh_tokens.append(refresh_token)
        return TikTokTokenSet("new-access", "new-refresh", 3600, ["shop.info"])


class FakeShopRepository:
    def __init__(self, shop_id: UUID) -> None:
        self.shop_id = shop_id
        self.refresh_token = "encrypted-refresh"
        self.refreshes: list[tuple[UUID, UUID, TikTokTokenSet]] = []
        self.disconnections: list[tuple[UUID, UUID]] = []
        self.scopes = ["seller.shop.info"]

    async def get_connection_status(
        self, tenant_id: UUID, shop_id: UUID
    ) -> dict[str, object] | None:
        if shop_id != self.shop_id:
            return None
        return {
            "shopId": str(shop_id),
            "platformShopId": "shop-001",
            "shopName": "Demo Shop",
            "status": "authorized",
            "expiresAt": datetime(2026, 8, 11, tzinfo=UTC),
            "scopes": self.scopes,
        }

    async def get_refresh_token(self, tenant_id: UUID, shop_id: UUID) -> str | None:
        return "refresh-secret" if shop_id == self.shop_id else None

    async def update_connection_tokens(
        self, tenant_id: UUID, shop_id: UUID, tokens: TikTokTokenSet
    ) -> bool:
        self.refreshes.append((tenant_id, shop_id, tokens))
        return shop_id == self.shop_id

    async def disconnect(self, tenant_id: UUID, shop_id: UUID) -> bool:
        self.disconnections.append((tenant_id, shop_id))
        return shop_id == self.shop_id


def _configure_connection_dependencies(
    monkeypatch, permissions: list[str], shop_id: UUID
):
    tenant_id = uuid4()
    user_id = uuid4()
    account = AuthAccount(
        user_id, tenant_id, "admin", hash_password("correct-password")
    )
    user = CurrentUser(user_id, "管理员", "admin", [], permissions)
    redis = FakeRedis()
    auth_service = AuthService(redis, captcha_hmac_secret="test-only-secret")
    access_token = asyncio.run(auth_service.create_session(account))
    tiktok_client = FakeTikTokClient()
    repository = FakeShopRepository(shop_id)
    authorization_service = TikTokAuthorizationService(
        redis,
        service_id="test-service-id",
        authorization_url="https://auth.example.test/authorize",
    )
    monkeypatch.setattr(app.state, "auth_service", auth_service)
    monkeypatch.setattr(app.state, "auth_repository", FakeAuthRepository(account, user))
    monkeypatch.setattr(app.state, "tiktok_client", tiktok_client, raising=False)
    monkeypatch.setattr(app.state, "shop_repository", repository, raising=False)
    monkeypatch.setattr(
        app.state,
        "tiktok_authorization_service",
        authorization_service,
        raising=False,
    )
    return (
        {"Authorization": f"Bearer {access_token}"},
        tiktok_client,
        repository,
        authorization_service,
    )


def test_connection_routes_refresh_disconnect_and_return_safe_status(
    monkeypatch,
) -> None:
    shop_id = uuid4()
    headers, tiktok_client, repository, _ = _configure_connection_dependencies(
        monkeypatch, ["shops:view", "shops:manage"], shop_id
    )

    with TestClient(app) as client:
        status_response = client.get(
            f"/api/v1/shops/tiktok/{shop_id}/connection", headers=headers
        )
        refresh_response = client.post(
            f"/api/v1/shops/tiktok/{shop_id}/refresh", headers=headers
        )
        disconnect_response = client.post(
            f"/api/v1/shops/tiktok/{shop_id}/disconnect", headers=headers
        )

    assert status_response.status_code == 200
    assert status_response.json() == {
        "shopId": str(shop_id),
        "platformShopId": "shop-001",
        "shopName": "Demo Shop",
        "status": "authorized",
        "expiresAt": "2026-08-11T00:00:00Z",
        "scopes": ["seller.shop.info"],
    }
    assert refresh_response.status_code == 200
    assert refresh_response.json()["status"] == "authorized"
    assert tiktok_client.refresh_tokens == ["refresh-secret"]
    assert repository.refreshes[0][2].access_token == "new-access"
    assert disconnect_response.status_code == 204
    assert repository.disconnections[0][1] == shop_id


def test_refresh_route_sets_tiktok_log_context(monkeypatch) -> None:
    shop_id = uuid4()
    headers, _, _, _ = _configure_connection_dependencies(
        monkeypatch, ["shops:manage"], shop_id
    )
    observed: list[tuple[str | None, str | None]] = []

    class ContextCheckingClient(FakeTikTokClient):
        async def refresh_access_token(self, refresh_token: str) -> TikTokTokenSet:
            del refresh_token
            context = get_tiktok_request_context()
            observed.append((context.tenant_id, context.shop_id))
            return TikTokTokenSet("new-access", "new-refresh", 3600, ["shop.info"])

    monkeypatch.setattr(
        app.state, "tiktok_client", ContextCheckingClient(), raising=False
    )

    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/shops/tiktok/{shop_id}/refresh", headers=headers
        )

    assert response.status_code == 200
    assert observed[0][1] == str(shop_id)


def test_connection_routes_enforce_module_permissions(monkeypatch) -> None:
    shop_id = uuid4()
    headers, _, _, _ = _configure_connection_dependencies(
        monkeypatch, ["shops:view"], shop_id
    )

    with TestClient(app) as client:
        status_response = client.get(
            f"/api/v1/shops/tiktok/{shop_id}/connection", headers=headers
        )
        refresh_response = client.post(
            f"/api/v1/shops/tiktok/{shop_id}/refresh", headers=headers
        )
        disconnect_response = client.post(
            f"/api/v1/shops/tiktok/{shop_id}/disconnect", headers=headers
        )

    assert status_response.status_code == 200
    assert refresh_response.status_code == 403
    assert disconnect_response.status_code == 403


def test_reauthorization_url_binds_shop_and_only_allows_missing_scope(
    monkeypatch,
) -> None:
    shop_id = uuid4()
    headers, _, repository, authorization_service = _configure_connection_dependencies(
        monkeypatch, ["shops:manage"], shop_id
    )

    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/shops/tiktok/{shop_id}/reauthorization-url",
            headers=headers,
        )

    assert response.status_code == 200
    state = response.json()["authorizationUrl"].split("state=")[1]
    context = asyncio.run(authorization_service.consume_state(state))
    assert context is not None
    assert context.shop_id == shop_id
    assert context.platform_shop_id == "shop-001"
    assert context.required_scopes == ("data.bestselling.public.read",)

    repository.scopes = ["data.bestselling.public.read"]
    with TestClient(app) as client:
        ready_response = client.post(
            f"/api/v1/shops/tiktok/{shop_id}/reauthorization-url",
            headers=headers,
        )

    assert ready_response.status_code == 409
