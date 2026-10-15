import asyncio

import httpx

from erp_api.services.tiktok_return_client import HttpTikTokReturnClient
from erp_api.services.tiktok_transport import TikTokTransport


def test_search_returns_uses_official_endpoint_and_retryable_post() -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={"data": {"return_orders": [], "next_page_token": ""}},
        )

    client = HttpTikTokReturnClient(
        TikTokTransport(
            base_url="https://open.example.test",
            app_key="app-key",
            app_secret="app-secret",
            http_transport=httpx.MockTransport(handler),
            clock=lambda: 1_700_000_000,
        )
    )
    page = asyncio.run(
        client.search_returns("access-token", shop_cipher="shop-cipher", page_size=20)
    )

    request = requests[0]
    assert request.method == "POST"
    assert request.url.path == "/return_refund/202602/returns/search"
    assert request.url.params["shop_cipher"] == "shop-cipher"
    assert request.url.params["page_size"] == "20"
    assert request.headers["x-tts-access-token"] == "access-token"
    assert page.returns == []
