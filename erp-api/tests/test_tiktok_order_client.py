import asyncio
from datetime import UTC, datetime

import httpx

from erp_api.services.tiktok_order_client import HttpTikTokOrderClient
from erp_api.services.tiktok_transport import TikTokTransport


def _client(handler) -> HttpTikTokOrderClient:
    return HttpTikTokOrderClient(
        TikTokTransport(
            base_url="https://open.example.test",
            app_key="app-key",
            app_secret="app-secret",
            http_transport=httpx.MockTransport(handler),
            clock=lambda: 1_700_000_000,
        )
    )


def test_list_orders_uses_signed_server_side_request_and_explicit_time_window() -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"data": {"orders": [], "next_page_token": ""}})

    asyncio.run(
        _client(handler).list_orders(
            "access-token",
            shop_cipher="shop-cipher",
            updated_from=datetime(2026, 8, 1, tzinfo=UTC),
            updated_to=datetime(2026, 8, 2, tzinfo=UTC),
        )
    )

    request = requests[0]
    assert request.method == "POST"
    assert request.url.path == "/order/202309/orders/search"
    assert request.url.params["shop_cipher"] == "shop-cipher"
    assert request.url.params["sign"]
    assert request.headers["x-tts-access-token"] == "access-token"
    assert b"update_time_ge" in request.content
    assert b"update_time_lt" in request.content


def test_get_order_uses_documented_ids_query_parameter() -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "data": {
                    "orders": [
                        {
                            "id": "order-1",
                            "status": "AWAITING_SHIPMENT",
                            "create_time": 1_700_000_000,
                            "update_time": 1_700_000_100,
                            "line_items": [],
                            "packages": [],
                        }
                    ]
                }
            },
        )

    order = asyncio.run(
        _client(handler).get_order(
            "access-token",
            shop_cipher="shop-cipher",
            order_id="order-1",
        )
    )

    request = requests[0]
    assert request.method == "GET"
    assert request.url.path == "/order/202309/orders"
    assert request.url.params["ids"] == "order-1"
    assert request.url.params["shop_cipher"] == "shop-cipher"
    assert request.url.params["sign"]
    assert request.headers["x-tts-access-token"] == "access-token"
    assert order.platform_order_id == "order-1"


def test_multiple_order_details_use_ids_batch_and_return_official_shipping_type():
    def handler(request):
        assert request.url.params["ids"] == "100,101"
        return httpx.Response(200, json={"data": {"orders": [{"id": number,
            "status": "IN_TRANSIT", "create_time": 1_700_000_000,
            "update_time": 1_700_000_100, "shipping_type": kind}
            for number, kind in [("100", "SELLER"), ("101", "TIKTOK")]]}})
    orders = asyncio.run(_client(handler).get_orders("token", shop_cipher="cipher", order_ids=["100", "101"]))
    assert [order.shipping_type for order in orders] == ["SELLER", "TIKTOK"]
