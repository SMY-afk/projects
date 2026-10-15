from __future__ import annotations

import asyncio
from urllib.parse import parse_qs, urlparse
from uuid import UUID, uuid4

from erp_api.core.config import Settings
from erp_api.main import _create_tiktok_authorization_service
from erp_api.services.tiktok_apps import (
    TikTokAppProfile,
    TikTokAppRegistry,
    TikTokAppTransport,
    TikTokMultiAppAuthorizationService,
)
from erp_api.services.tiktok_authorization import TikTokAuthorizationService
from erp_api.services.tiktok_transport import (
    TikTokRequest,
    TikTokResponse,
    tiktok_request_context,
)


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


class FakeShopRepository:
    def __init__(self, profile: str = "301") -> None:
        self.profile = profile
        self.lookups: list[tuple[UUID, UUID]] = []

    async def get_app_profile(self, tenant_id: UUID, shop_id: UUID) -> str:
        self.lookups.append((tenant_id, shop_id))
        return self.profile


class RecordingTransport:
    def __init__(self, profile: str) -> None:
        self.profile = profile
        self.calls = 0

    async def request_with_metadata(self, request, **kwargs) -> TikTokResponse:
        del request, kwargs
        self.calls += 1
        return TikTokResponse({"profile": self.profile}, None, 200)


def _registry(repository: FakeShopRepository) -> TikTokAppRegistry:
    return TikTokAppRegistry(
        {
            "legacy": TikTokAppProfile("legacy", "legacy-key", "secret", "old"),
            "301": TikTokAppProfile("301", "301-key", "secret", "new"),
        },
        repository,
        timeout_seconds=10,
        max_retries=0,
        retry_base_seconds=0,
        max_retry_delay_seconds=0,
    )


def test_transport_selects_301_from_shop_connection_context() -> None:
    tenant_id = uuid4()
    shop_id = uuid4()
    repository = FakeShopRepository("301")
    legacy = RecordingTransport("legacy")
    app_301 = RecordingTransport("301")
    transport = TikTokAppTransport(
        {"legacy": legacy, "301": app_301}, _registry(repository)
    )

    async def request() -> TikTokResponse:
        with tiktok_request_context(tenant_id=str(tenant_id), shop_id=str(shop_id)):
            return await transport.request_with_metadata(TikTokRequest("GET", "/test"))

    response = asyncio.run(request())

    assert response.payload == {"profile": "301"}
    assert repository.lookups == [(tenant_id, shop_id)]
    assert legacy.calls == 0
    assert app_301.calls == 1


def test_oauth_state_and_missing_state_callback_remain_bound_to_301() -> None:
    redis = FakeRedis()
    repository = FakeShopRepository()
    registry = _registry(repository)
    services = {
        "legacy": TikTokAuthorizationService(
            redis,
            service_id="old-service",
            authorization_url="https://auth.test/authorize",
            app_key="legacy-key",
        ),
        "301": TikTokAuthorizationService(
            redis,
            service_id="301-service",
            authorization_url="https://auth.test/authorize",
            app_key="301-key",
            app_profile="301",
        ),
    }
    coordinator = TikTokMultiAppAuthorizationService(services, registry)
    user_id = uuid4()
    tenant_id = uuid4()

    authorization_url = asyncio.run(
        coordinator.create_authorization_url(user_id, tenant_id, app_profile="301")
    )
    query = parse_qs(urlparse(authorization_url).query)
    state = query["state"][0]
    context = asyncio.run(coordinator.consume_callback_state(state, app_key="301-key"))

    assert query["service_id"] == ["301-service"]
    assert context is not None
    assert context.app_profile == "301"

    asyncio.run(
        coordinator.create_authorization_url(user_id, tenant_id, app_profile="301")
    )
    missing_state_context = asyncio.run(
        coordinator.consume_callback_state(None, app_key="301-key")
    )
    assert missing_state_context is not None
    assert missing_state_context.app_profile == "301"


def test_301_oauth_uses_its_us_seller_authorization_entry() -> None:
    redis = FakeRedis()
    registry = _registry(FakeShopRepository())
    settings = Settings(
        database_url="sqlite+aiosqlite://",
        redis_url="redis://localhost:6379/0",
        tiktok_app_key="legacy-key",
        tiktok_app_secret="legacy-secret",
        tiktok_service_id="legacy-service",
        tiktok_301_app_key="301-key",
        tiktok_301_app_secret="301-secret",
        tiktok_301_service_id="301-service",
        tiktok_authorization_url="https://services.tiktokshop.com/open/authorize",
        tiktok_301_authorization_url=(
            "https://services.us.tiktokshop.com/open/authorize"
        ),
    )
    coordinator = _create_tiktok_authorization_service(settings, redis, registry)

    authorization_url = asyncio.run(
        coordinator.create_authorization_url(uuid4(), uuid4(), app_profile="301")
    )

    assert urlparse(authorization_url).netloc == "services.us.tiktokshop.com"
