from __future__ import annotations

import asyncio
from urllib.parse import parse_qs, urlparse
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from test_tiktok_authorization import (
    FakeRedis,
    FakeShopRepository,
    FakeTikTokClient,
)

from erp_api.main import app
from erp_api.services.tiktok_authorization import TikTokAuthorizationService

REQUIRED_SCOPE = "data.bestselling.public.read"
SHOP_ID = UUID("b252abf4-86c8-539b-956f-1fd1b0892dfe")


class FakeReauthorizationRepository:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, UUID, str, object, object, str]] = []

    async def replace_connection(
        self,
        tenant_id: UUID,
        shop_id: UUID,
        platform_shop_id: str,
        identity: object,
        tokens: object,
        *,
        app_profile: str,
    ) -> object:
        self.calls.append(
            (tenant_id, shop_id, platform_shop_id, identity, tokens, app_profile)
        )
        return type("ShopResult", (), {"id": shop_id})()


@pytest.mark.parametrize(
    ("scopes", "platform_shop_id", "expected_status", "expected_upserts"),
    [
        ([REQUIRED_SCOPE], "shop-001", 200, 1),
        (["seller.shop.info"], "shop-001", 409, 0),
        ([REQUIRED_SCOPE], "shop-002", 502, 0),
    ],
)
def test_reauthorization_callback_validates_scope_and_target_before_upsert(
    monkeypatch,
    scopes: list[str],
    platform_shop_id: str,
    expected_status: int,
    expected_upserts: int,
) -> None:
    tenant_id = uuid4()
    redis = FakeRedis()
    authorization_service = TikTokAuthorizationService(
        redis,
        service_id="test-service-id",
        authorization_url="https://auth.example.test/authorize",
    )
    authorization_url = asyncio.run(
        authorization_service.create_reauthorization_url(
            uuid4(),
            tenant_id,
            shop_id=SHOP_ID,
            platform_shop_id="shop-001",
            required_scopes=[REQUIRED_SCOPE],
        )
    )
    state = parse_qs(urlparse(authorization_url).query)["state"][0]
    repository = FakeShopRepository()
    reauthorization_repository = FakeReauthorizationRepository()
    monkeypatch.setattr(
        app.state, "tiktok_authorization_service", authorization_service, raising=False
    )
    monkeypatch.setattr(
        app.state,
        "tiktok_client",
        FakeTikTokClient(scopes=scopes, platform_shop_id=platform_shop_id),
        raising=False,
    )
    monkeypatch.setattr(app.state, "shop_repository", repository, raising=False)
    monkeypatch.setattr(
        app.state,
        "tiktok_reauthorization_repository",
        reauthorization_repository,
        raising=False,
    )

    with TestClient(app) as client:
        response = client.get(
            f"/api/v1/shops/tiktok/callback?code=auth-code&state={state}"
        )

    assert response.status_code == expected_status
    assert repository.calls == []
    assert len(reauthorization_repository.calls) == expected_upserts
