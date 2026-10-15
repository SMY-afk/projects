from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from erp_api.services.platform_fulfillment_adapter import (
    PlatformFulfillmentCommand,
    PlatformFulfillmentError,
)
from erp_api.services.tiktok_fulfillment_adapter import TikTokFulfillmentAdapter
from erp_api.services.tiktok_schemas import TikTokTokenSet
from erp_api.services.tiktok_transport import (
    TikTokApiError,
    get_tiktok_request_context,
)


class FakeShopRepository:
    def __init__(
        self,
        *,
        expires_at=None,
        access_token="old-access-token",
        refresh_token="refresh-token",
        shop_cipher="shop-cipher",
        update_success=True,
    ) -> None:
        self.expires_at = expires_at or datetime.now(UTC) + timedelta(hours=1)
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.shop_cipher = shop_cipher
        self.update_success = update_success
        self.updated = []

    async def get_access_token(self, tenant_id, shop_id):
        return self.access_token

    async def get_connection_tokens(self, tenant_id, shop_id):
        return self.refresh_token, self.expires_at, self.shop_cipher

    async def update_connection_tokens(self, tenant_id, shop_id, tokens):
        self.updated.append(tokens)
        return self.update_success


class FakeTokenClient:
    def __init__(self) -> None:
        self.refreshes = []

    async def refresh_access_token(self, refresh_token):
        self.refreshes.append((refresh_token, get_tiktok_request_context()))
        return TikTokTokenSet(
            access_token="new-access-token",
            refresh_token="new-refresh-token",
            expires_in=3600,
            scopes=["seller.fulfillment.basic"],
        )


class FakeFulfillmentClient:
    def __init__(self, error=None) -> None:
        self.calls = []
        self.error = error

    async def ship_package(self, access_token, **kwargs):
        self.calls.append((access_token, kwargs, get_tiktok_request_context()))
        if self.error:
            raise self.error
        return "request-1"


def _command(**changes):
    values = {
        "event_id": uuid4(),
        "tenant_id": uuid4(),
        "shop_id": uuid4(),
        "platform": "tiktok",
        "platform_order_id": "order-1",
        "platform_package_id": "package-1",
        "tracking_number": "TRACK-1",
        "platform_carrier_id": "provider-1",
        "shipped_at": datetime.now(UTC),
        "idempotency_key": "shipment:1",
    }
    values.update(changes)
    return PlatformFulfillmentCommand(**values)


@pytest.mark.asyncio
async def test_adapter_sends_seller_shipment_with_shop_credentials() -> None:
    fulfillment_client = FakeFulfillmentClient()
    adapter = TikTokFulfillmentAdapter(
        FakeShopRepository(), FakeTokenClient(), fulfillment_client
    )
    command = _command()

    result = await adapter.fulfill(command)

    assert result.platform_request_id == "request-1"
    access_token, payload, context = fulfillment_client.calls[0]
    assert access_token == "old-access-token"
    assert payload == {
        "shop_cipher": "shop-cipher",
        "platform_package_id": "package-1",
        "tracking_number": "TRACK-1",
        "shipping_provider_id": "provider-1",
    }
    assert context.tenant_id == str(command.tenant_id)
    assert context.shop_id == str(command.shop_id)


@pytest.mark.asyncio
async def test_adapter_refreshes_expiring_token_before_shipping() -> None:
    repository = FakeShopRepository(
        expires_at=datetime.now(UTC) + timedelta(seconds=30)
    )
    token_client = FakeTokenClient()
    fulfillment_client = FakeFulfillmentClient()
    adapter = TikTokFulfillmentAdapter(repository, token_client, fulfillment_client)
    command = _command()

    await adapter.fulfill(command)

    assert token_client.refreshes[0][0] == "refresh-token"
    assert token_client.refreshes[0][1].tenant_id == str(command.tenant_id)
    assert token_client.refreshes[0][1].shop_id == str(command.shop_id)
    assert len(repository.updated) == 1
    assert fulfillment_client.calls[0][0] == "new-access-token"


@pytest.mark.asyncio
async def test_adapter_refreshes_when_access_token_is_missing() -> None:
    repository = FakeShopRepository(access_token=None)
    token_client = FakeTokenClient()
    fulfillment_client = FakeFulfillmentClient()
    adapter = TikTokFulfillmentAdapter(repository, token_client, fulfillment_client)

    await adapter.fulfill(_command())

    assert token_client.refreshes[0][0] == "refresh-token"
    assert fulfillment_client.calls[0][0] == "new-access-token"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("repository", "code", "retryable"),
    [
        (
            FakeShopRepository(access_token=None, refresh_token=None),
            "platform_credentials_unavailable",
            False,
        ),
        (
            FakeShopRepository(shop_cipher=None),
            "platform_credentials_unavailable",
            False,
        ),
        (
            FakeShopRepository(expires_at=datetime.now(UTC), refresh_token=None),
            "platform_token_expired",
            False,
        ),
        (
            FakeShopRepository(expires_at=datetime.now(UTC), update_success=False),
            "platform_token_refresh_failed",
            True,
        ),
    ],
)
async def test_adapter_classifies_credential_failures(
    repository, code, retryable
) -> None:
    fulfillment_client = FakeFulfillmentClient()
    adapter = TikTokFulfillmentAdapter(
        repository, FakeTokenClient(), fulfillment_client
    )

    with pytest.raises(PlatformFulfillmentError) as raised:
        await adapter.fulfill(_command())

    assert raised.value.code == code
    assert raised.value.retryable is retryable
    assert fulfillment_client.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"platform_package_id": None}, "platform_package_mapping_required"),
        ({"platform_carrier_id": None}, "platform_carrier_mapping_required"),
        ({"tracking_number": "   "}, "tracking_number_required"),
        ({"platform": "other"}, "platform_adapter_mismatch"),
    ],
)
async def test_adapter_rejects_incomplete_platform_mapping(changes, code) -> None:
    adapter = TikTokFulfillmentAdapter(
        FakeShopRepository(), FakeTokenClient(), FakeFulfillmentClient()
    )

    with pytest.raises(PlatformFulfillmentError) as raised:
        await adapter.fulfill(_command(**changes))

    assert raised.value.code == code
    assert raised.value.retryable is False


@pytest.mark.asyncio
async def test_adapter_strips_external_identifiers_before_sending() -> None:
    fulfillment_client = FakeFulfillmentClient()
    adapter = TikTokFulfillmentAdapter(
        FakeShopRepository(), FakeTokenClient(), fulfillment_client
    )

    await adapter.fulfill(
        _command(
            platform_package_id=" package-1 ",
            tracking_number=" TRACK-1 ",
            platform_carrier_id=" provider-1 ",
        )
    )

    assert fulfillment_client.calls[0][1]["platform_package_id"] == "package-1"
    assert fulfillment_client.calls[0][1]["tracking_number"] == "TRACK-1"
    assert fulfillment_client.calls[0][1]["shipping_provider_id"] == "provider-1"


@pytest.mark.asyncio
async def test_adapter_treats_already_shipped_response_as_idempotent_success() -> None:
    error = TikTokApiError(
        "rejected",
        code="21011040",
        status_code=502,
        request_id="request-already-shipped",
        upstream_status_code=200,
    )
    adapter = TikTokFulfillmentAdapter(
        FakeShopRepository(), FakeTokenClient(), FakeFulfillmentClient(error)
    )

    result = await adapter.fulfill(_command())

    assert result.platform_request_id == "request-already-shipped"
