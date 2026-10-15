from __future__ import annotations

import asyncio
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from erp_api.main import app
from erp_api.services.auth import AuthAccount, AuthService, CurrentUser, hash_password
from erp_api.services.tiktok_authorization import TikTokAuthorizationService
from erp_api.services.tiktok_client import TikTokShopIdentity, TikTokTokenSet
from erp_api.services.token_cipher import TokenCipher


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.expiries: list[int] = []

    async def set(self, key: str, value: str, *, ex: int) -> None:
        self.values[key] = value
        self.expiries.append(ex)

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
    def __init__(
        self,
        *,
        scopes: list[str] | None = None,
        platform_shop_id: str = "shop-001",
    ) -> None:
        self.scopes = scopes or ["shop.info"]
        self.platform_shop_id = platform_shop_id
        self.shop_identity_calls = 0

    async def exchange_code(self, code: str) -> TikTokTokenSet:
        assert code == "auth-code"
        return TikTokTokenSet("access-secret", "refresh-secret", 3600, self.scopes)

    async def get_shop_identity(self, access_token: str) -> TikTokShopIdentity:
        assert access_token == "access-secret"
        self.shop_identity_calls += 1
        return TikTokShopIdentity(self.platform_shop_id, "Demo Shop", "US")

    async def get_authorized_shops(self, access_token: str) -> list[TikTokShopIdentity]:
        assert access_token == "access-secret"
        return [
            TikTokShopIdentity(self.platform_shop_id, "Demo Shop", "US", "shop-cipher")
        ]


class FakeShopRepository:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, TikTokShopIdentity, TikTokTokenSet, str]] = []

    async def upsert_tiktok_shop(
        self,
        tenant_id: UUID,
        identity: TikTokShopIdentity,
        tokens: TikTokTokenSet,
        *,
        app_profile: str = "legacy",
    ):
        self.calls.append((tenant_id, identity, tokens, app_profile))
        return type(
            "ShopResult", (), {"id": UUID("b252abf4-86c8-539b-956f-1fd1b0892dfe")}
        )()

    async def get_connection_status(
        self, tenant_id: UUID, shop_id: UUID | None
    ) -> dict[str, object] | None:
        del tenant_id
        if shop_id != UUID("b252abf4-86c8-539b-956f-1fd1b0892dfe"):
            return None
        return {
            "shopId": str(shop_id),
            "platformShopId": "shop-001",
            "status": "authorized",
            "scopes": ["seller.shop.info"],
        }


def test_authorization_url_binds_and_consumes_state_once(monkeypatch) -> None:
    tenant_id = uuid4()
    user_id = uuid4()
    account = AuthAccount(
        id=user_id,
        tenant_id=tenant_id,
        username="admin",
        password_hash=hash_password("correct-password"),
    )
    user = CurrentUser(
        id=user_id,
        name="管理员",
        username="admin",
        roles=[],
        permissions=["shops:manage"],
    )
    redis = FakeRedis()
    auth_service = AuthService(redis, captcha_hmac_secret="test-only-secret")
    access_token = asyncio.run(auth_service.create_session(account))
    authorization_service = TikTokAuthorizationService(
        redis,
        service_id="test-service-id",
        authorization_url="https://auth.example.test/authorize",
        state_ttl_seconds=600,
    )
    monkeypatch.setattr(app.state, "auth_service", auth_service)
    monkeypatch.setattr(app.state, "auth_repository", FakeAuthRepository(account, user))
    monkeypatch.setattr(
        app.state, "tiktok_authorization_service", authorization_service, raising=False
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/shops/tiktok/authorization-url",
            headers={"Authorization": f"Bearer {access_token}"},
        )

    assert response.status_code == 200
    authorization_url = response.json()["authorizationUrl"]
    query = parse_qs(urlparse(authorization_url).query)
    assert query["service_id"] == ["test-service-id"]
    assert "app_key" not in query
    assert "redirect_uri" not in query
    state = query["state"][0]
    state_context = asyncio.run(authorization_service.consume_state(state))
    assert state_context is not None
    assert state_context.user_id == user_id
    assert state_context.tenant_id == tenant_id
    assert state_context.intent == "authorize"
    assert asyncio.run(authorization_service.consume_state(state)) is None
    assert redis.expiries[-1] == 600


def test_reauthorization_state_binds_target_shop_and_requires_explicit_state() -> None:
    tenant_id = uuid4()
    user_id = uuid4()
    shop_id = uuid4()
    redis = FakeRedis()
    authorization_service = TikTokAuthorizationService(
        redis,
        service_id="test-service-id",
        authorization_url="https://auth.example.test/authorize",
    )

    authorization_url = asyncio.run(
        authorization_service.create_reauthorization_url(
            user_id,
            tenant_id,
            shop_id=shop_id,
            platform_shop_id="shop-001",
            required_scopes=["data.bestselling.public.read"],
        )
    )
    state = parse_qs(urlparse(authorization_url).query)["state"][0]

    assert asyncio.run(authorization_service.consume_callback_state(None)) is None
    context = asyncio.run(authorization_service.consume_callback_state(state))
    assert context is not None
    assert context.user_id == user_id
    assert context.tenant_id == tenant_id
    assert context.shop_id == shop_id
    assert context.platform_shop_id == "shop-001"
    assert context.intent == "scope_upgrade"
    assert context.required_scopes == ("data.bestselling.public.read",)
    assert asyncio.run(authorization_service.consume_callback_state(state)) is None


def test_callback_validates_state_exchanges_code_and_upserts_shop(monkeypatch) -> None:
    tenant_id = uuid4()
    user_id = uuid4()
    redis = FakeRedis()
    authorization_service = TikTokAuthorizationService(
        redis,
        service_id="test-service-id",
        authorization_url="https://auth.example.test/authorize",
    )
    state = asyncio.run(
        authorization_service.create_authorization_url(user_id, tenant_id)
    ).split("state=")[1]
    client = FakeTikTokClient()
    repository = FakeShopRepository()
    monkeypatch.setattr(
        app.state, "tiktok_authorization_service", authorization_service, raising=False
    )
    monkeypatch.setattr(app.state, "tiktok_client", client, raising=False)
    monkeypatch.setattr(app.state, "shop_repository", repository, raising=False)

    with TestClient(app) as test_client:
        response = test_client.get(
            f"/api/v1/shops/tiktok/callback?code=auth-code&state={state}"
        )
        replay = test_client.get(
            f"/api/v1/shops/tiktok/callback?code=auth-code&state={state}"
        )

    assert response.status_code == 200
    assert response.json() == {
        "shopId": "b252abf4-86c8-539b-956f-1fd1b0892dfe",
        "platformShopId": "shop-001",
        "status": "authorized",
    }
    assert replay.status_code == 400
    assert repository.calls[0][0] == tenant_id
    assert repository.calls[0][2].access_token == "access-secret"
    assert client.shop_identity_calls == 0


def test_callback_accepts_tiktok_callback_without_state_once(monkeypatch) -> None:
    tenant_id = uuid4()
    user_id = uuid4()
    redis = FakeRedis()
    authorization_service = TikTokAuthorizationService(
        redis,
        service_id="test-service-id",
        authorization_url="https://auth.example.test/authorize",
    )
    asyncio.run(authorization_service.create_authorization_url(user_id, tenant_id))
    client = FakeTikTokClient()
    repository = FakeShopRepository()
    monkeypatch.setattr(
        app.state, "tiktok_authorization_service", authorization_service, raising=False
    )
    monkeypatch.setattr(app.state, "tiktok_client", client, raising=False)
    monkeypatch.setattr(app.state, "shop_repository", repository, raising=False)

    with TestClient(app) as test_client:
        response = test_client.get("/api/v1/shops/tiktok/callback?code=auth-code")
        replay = test_client.get("/api/v1/shops/tiktok/callback?code=auth-code")

    assert response.status_code == 200
    assert replay.status_code == 400


def test_token_cipher_round_trips_without_storing_plaintext() -> None:
    cipher = TokenCipher("test-only-token-encryption-key-32-chars")
    encrypted = cipher.encrypt("access-secret")

    assert encrypted != "access-secret"
    assert cipher.decrypt(encrypted) == "access-secret"
