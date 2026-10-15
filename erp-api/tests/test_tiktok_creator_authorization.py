from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from erp_api.main import app
from erp_api.services.creator_connection_repository import (
    CreatorAuthorizationError,
    CreatorConnectionRepository,
)
from erp_api.services.tiktok_authorization import TikTokAuthorizationService
from erp_api.services.tiktok_schemas import TikTokTokenSet, parse_token_response
from erp_api.services.token_cipher import TokenCipher


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


class FakeCreatorClient:
    def __init__(self, tokens: TikTokTokenSet) -> None:
        self.tokens = tokens
        self.seller_identity_called = False

    async def exchange_code(self, code: str) -> TikTokTokenSet:
        assert code == "creator-auth-code"
        return self.tokens

    async def get_shop_identity(self, access_token: str):
        del access_token
        self.seller_identity_called = True
        raise AssertionError("Creator callback must not call Seller identity APIs.")

    async def get_authorized_shops(self, access_token: str):
        del access_token
        raise AssertionError("Creator callback must not call Seller shop APIs.")


class FakeCreatorRepository:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, UUID, TikTokTokenSet]] = []

    async def upsert_authorization(
        self, tenant_id: UUID, user_id: UUID, tokens: TikTokTokenSet
    ):
        self.calls.append((tenant_id, user_id, tokens))
        if tokens.user_type != 1:
            raise CreatorAuthorizationError("not a creator")
        return SimpleNamespace(
            id=UUID("b7daa4ef-8501-5ec2-9bc1-5923269f8494"),
            open_id=tokens.open_id,
        )


def _authorization_service(redis: FakeRedis) -> TikTokAuthorizationService:
    return TikTokAuthorizationService(
        redis,
        service_id="seller-service-id",
        authorization_url="https://seller.example.test/authorize",
        app_key="creator-app-key",
        creator_authorization_url=("https://shop.tiktok.com/alliance/creator/auth"),
    )


def test_creator_authorization_url_uses_app_key_and_strict_creator_state() -> None:
    redis = FakeRedis()
    service = _authorization_service(redis)
    user_id, tenant_id = uuid4(), uuid4()

    authorization_url = asyncio.run(
        service.create_creator_authorization_url(user_id, tenant_id)
    )
    query = parse_qs(urlparse(authorization_url).query)
    state = query["state"][0]

    assert query["app_key"] == ["creator-app-key"]
    assert "service_id" not in query
    assert asyncio.run(service.consume_callback_state(None)) is None
    context = asyncio.run(service.consume_callback_state(state))
    assert context is not None
    assert context.intent == "creator_authorize"
    assert context.user_id == user_id
    assert context.tenant_id == tenant_id
    assert asyncio.run(service.consume_callback_state(state)) is None


def test_creator_token_response_preserves_subject_scope_and_expiry(monkeypatch) -> None:
    monkeypatch.setattr(
        "erp_api.services.tiktok_schemas.time.time", lambda: 1_700_000_000
    )

    tokens = parse_token_response(
        {
            "code": 0,
            "data": {
                "access_token": "creator-access-secret",
                "refresh_token": "creator-refresh-secret",
                "access_token_expire_in": 1_700_003_600,
                "refresh_token_expire_in": 1_700_007_200,
                "open_id": "creator-open-id",
                "user_type": 1,
                "seller_base_region": "US",
                "granted_scopes": ["creator.video.write"],
            },
        }
    )

    assert tokens.open_id == "creator-open-id"
    assert tokens.user_type == 1
    assert tokens.region == "US"
    assert tokens.expires_in == 3600
    assert tokens.refresh_expires_in == 7200
    assert tokens.scopes == ["creator.video.write"]


def test_shared_callback_persists_creator_without_calling_seller_apis(
    monkeypatch,
) -> None:
    redis = FakeRedis()
    service = _authorization_service(redis)
    user_id, tenant_id = uuid4(), uuid4()
    authorization_url = asyncio.run(
        service.create_creator_authorization_url(user_id, tenant_id)
    )
    state = parse_qs(urlparse(authorization_url).query)["state"][0]
    tokens = TikTokTokenSet(
        "creator-access-secret",
        "creator-refresh-secret",
        3600,
        ["creator.video.write"],
        open_id="creator-open-id",
        user_type=1,
    )
    client = FakeCreatorClient(tokens)
    repository = FakeCreatorRepository()
    monkeypatch.setattr(
        app.state, "tiktok_authorization_service", service, raising=False
    )
    monkeypatch.setattr(app.state, "tiktok_client", client, raising=False)
    monkeypatch.setattr(
        app.state, "creator_connection_repository", repository, raising=False
    )

    with TestClient(app) as test_client:
        response = test_client.get(
            "/api/v1/shops/tiktok/callback",
            params={"code": "creator-auth-code", "state": state},
        )

    assert response.status_code == 200
    assert response.json() == {
        "creatorConnectionId": "b7daa4ef-8501-5ec2-9bc1-5923269f8494",
        "openId": "creator-open-id",
        "subjectType": "creator",
        "status": "authorized",
    }
    assert repository.calls == [(tenant_id, user_id, tokens)]
    assert client.seller_identity_called is False


class CapturingSession:
    def __init__(self) -> None:
        self.statement = None
        self.committed = False

    async def scalar(self, statement):
        self.statement = statement
        return UUID("61cc6eb7-64e6-58cc-bb3d-c64d4c5bf104")

    async def commit(self) -> None:
        self.committed = True


class FakeDatabase:
    def __init__(self, session: CapturingSession) -> None:
        self.fake_session = session

    async def session(self, tenant_id: UUID):
        del tenant_id
        yield self.fake_session


def test_repository_encrypts_creator_tokens_before_building_upsert() -> None:
    session = CapturingSession()
    repository = CreatorConnectionRepository(
        FakeDatabase(session),
        TokenCipher("test-only-token-encryption-key-32-chars"),
    )
    tokens = TikTokTokenSet(
        "creator-access-secret",
        "creator-refresh-secret",
        3600,
        ["creator.video.write"],
        open_id="creator-open-id",
        user_type=1,
        refresh_expires_in=7200,
        region="US",
    )

    result = asyncio.run(repository.upsert_authorization(uuid4(), uuid4(), tokens))
    params = session.statement.compile().params

    assert result.open_id == "creator-open-id"
    assert session.committed is True
    assert "creator-access-secret" not in repr(params)
    assert "creator-refresh-secret" not in repr(params)
    assert datetime.now(UTC).timestamp() < result.expires_at.timestamp()
