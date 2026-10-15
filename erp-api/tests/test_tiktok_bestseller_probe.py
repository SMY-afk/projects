from __future__ import annotations

import asyncio

import httpx

from erp_api.services.tiktok_bestseller_probe import TikTokBestsellerProbe
from erp_api.services.tiktok_transport import TikTokTransport


def test_probe_records_only_status_request_id_and_field_names() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        node = request.url.path.split("/")[-2]
        item_node = {
            "products": "products",
            "creators": "creators",
            "videos": "videos",
            "lives": "lives",
        }[node]
        return httpx.Response(
            200,
            headers={"x-tts-request-id": f"request-{node}"},
            json={
                "code": 0,
                "message": "Success",
                "data": {item_node: [{"rank": 1, "secret_value": "do-not-log"}]},
            },
        )

    probe = TikTokBestsellerProbe(
        TikTokTransport(
            base_url="https://open.example.test",
            app_key="app-key",
            app_secret="app-secret",
            max_retries=0,
            http_transport=httpx.MockTransport(handler),
        )
    )

    results = asyncio.run(
        probe.run(
            access_token="access-secret",
            shop_cipher="shop-secret",
            date="2026-08-19",
            time_slot="7D",
            currency="USD",
            author_type="ALL",
        )
    )

    assert len(results) == 4
    assert set(results[0]) == {
        "api",
        "httpStatus",
        "tiktokCode",
        "requestId",
        "fieldNames",
    }
    assert results[0]["fieldNames"] == {
        "envelope": ["code", "data", "message"],
        "data": ["products"],
        "item": ["rank", "secret_value"],
    }
    assert "do-not-log" not in str(results)
    assert "access-secret" not in str(results)
    assert "shop-secret" not in str(results)
    assert requests[1].url.params["author_type"] == "ALL"
    assert all(request.url.params["date"] == "2026-08-19" for request in requests)
