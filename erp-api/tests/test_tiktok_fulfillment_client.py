from types import SimpleNamespace

import pytest

from erp_api.services.tiktok_fulfillment_client import HttpTikTokFulfillmentClient


class FakeTransport:
    def __init__(self) -> None:
        self.request = None
        self.access_token = None

    async def request_with_metadata(self, request, *, access_token):
        self.request = request
        self.access_token = access_token
        return SimpleNamespace(platform_request_id="request-1")


@pytest.mark.asyncio
async def test_tiktok_client_sends_self_shipment_contract() -> None:
    transport = FakeTransport()
    client = HttpTikTokFulfillmentClient(
        transport,
        ship_path_template="/fulfillment/202309/packages/{package_id}/ship",
    )

    request_id = await client.ship_package(
        "access-token",
        shop_cipher="shop-cipher",
        platform_package_id="package/1",
        tracking_number="TRACK-123",
        shipping_provider_id="provider-1",
    )

    assert request_id == "request-1"
    assert transport.request.path.endswith("/package%2F1/ship")
    assert transport.request.query == {"shop_cipher": "shop-cipher"}
    assert transport.request.json_body == {
        "self_shipment": {
            "tracking_number": "TRACK-123",
            "shipping_provider_id": "provider-1",
        },
    }
    assert transport.request.retryable is False
    assert transport.access_token == "access-token"


def test_tiktok_client_requires_package_placeholder() -> None:
    with pytest.raises(ValueError):
        HttpTikTokFulfillmentClient(FakeTransport(), ship_path_template="/ship")
