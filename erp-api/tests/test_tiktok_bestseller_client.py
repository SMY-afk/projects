from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from erp_api.services.tiktok_bestseller_client import HttpTikTokBestsellerClient
from erp_api.services.tiktok_transport import TikTokTransport


def test_factory_reuses_existing_tiktok_api_transport() -> None:
    from erp_api.main import _create_tiktok_bestseller_client

    transport = TikTokTransport(
        base_url="https://open.example.test",
        app_key="app-key",
        app_secret="app-secret",
    )

    client = _create_tiktok_bestseller_client(SimpleNamespace(api_transport=transport))

    assert client is not None
    assert client._transport is transport
    assert _create_tiktok_bestseller_client(None) is None


def _client(
    handler,
    *,
    max_retries: int = 0,
    sleep=asyncio.sleep,
) -> HttpTikTokBestsellerClient:
    return HttpTikTokBestsellerClient(
        TikTokTransport(
            base_url="https://open.example.test",
            app_key="app-key",
            app_secret="app-secret",
            max_retries=max_retries,
            retry_base_seconds=0.25,
            http_transport=httpx.MockTransport(handler),
            sleep=sleep,
            clock=lambda: 1_700_000_000,
        )
    )


@pytest.mark.parametrize(
    ("method_name", "node", "extra_query"),
    [
        ("list_products", "products", {}),
        ("list_creators", "creators", {"author_type": "AFFILIATE"}),
        ("list_videos", "videos", {}),
        ("list_lives", "lives", {}),
    ],
)
def test_four_requests_use_date_time_slot_and_existing_transport_signature(
    method_name: str,
    node: str,
    extra_query: dict[str, str],
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            headers={"x-tts-request-id": f"request-{node}"},
            json={"code": 0, "data": {node: []}},
        )

    method = getattr(_client(handler), method_name)
    result = asyncio.run(
        method(
            "access-token",
            shop_cipher="shop-cipher",
            date="2026-08-19",
            time_slot="7D",
            currency="USD",
            **extra_query,
        )
    )

    request = requests[0]
    assert request.method == "GET"
    assert request.url.path == f"/analytics/202511/{node}/bestselling"
    assert request.url.params["shop_cipher"] == "shop-cipher"
    assert request.url.params["date"] == "2026-08-19"
    assert request.url.params["time_slot"] == "7D"
    assert request.url.params["currency"] == "USD"
    assert request.url.params.get("author_type") == extra_query.get("author_type")
    assert request.url.params["app_key"] == "app-key"
    assert request.url.params["timestamp"] == "1700000000"
    assert request.url.params["sign"]
    assert "app_secret" not in request.url.params
    assert request.headers["x-tts-access-token"] == "access-token"
    assert result.platform_request_id == f"request-{node}"


@pytest.mark.parametrize(
    ("method_name", "overrides", "message"),
    [
        ("list_products", {"date": "2026/08/19"}, "YYYY-MM-DD"),
        ("list_creators", {"time_slot": "14D"}, "time_slot"),
        ("list_videos", {"currency": "EUR"}, "currency"),
        ("list_lives", {"shop_cipher": ""}, "shop_cipher"),
        ("list_creators", {"author_type": "UNKNOWN"}, "author_type"),
    ],
)
def test_request_parameters_fail_before_transport(
    method_name: str,
    overrides: dict[str, str],
    message: str,
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    arguments = {
        "shop_cipher": "shop-cipher",
        "date": "2026-08-19",
        "time_slot": "7D",
        "currency": "USD",
    }
    arguments.update(overrides)
    if method_name == "list_creators":
        arguments.setdefault("author_type", "ALL")

    with pytest.raises(ValueError, match=message):
        asyncio.run(getattr(_client(handler), method_name)("token", **arguments))

    assert calls == 0


@pytest.mark.parametrize(
    ("method_name", "node", "item", "expected"),
    [
        (
            "list_products",
            "products",
            {
                "id": "product-1",
                "rank": 1,
                "name": "Toy",
                "gmv_range": "$1K-$2K",
                "rating": "4.8",
                "product_image": {"uri": "image-1"},
            },
            ("product", "product-1", "Toy", {"rating", "product_image"}),
        ),
        (
            "list_creators",
            "creators",
            {
                "open_id": "creator-1",
                "rank": 2,
                "nick_name": "Creator",
                "gmv_range": "$2K-$3K",
                "followers_count": 100,
            },
            ("creator", "creator-1", "Creator", {"followers_count"}),
        ),
        (
            "list_videos",
            "videos",
            {
                "id": "video-1",
                "rank": 3,
                "nick_name": "Video Creator",
                "gmv_range": "$3K-$4K",
                "views": 500,
                "product_infos": [{"product_id": "product-1"}],
            },
            ("video", "video-1", "Video Creator", {"views", "product_infos"}),
        ),
        (
            "list_lives",
            "lives",
            {
                "id": "live-1",
                "rank": 4,
                "title": "LIVE",
                "gmv_range": "$4K-$5K",
                "duration": 3600,
                "creator_name": "host",
            },
            ("live", "live-1", "LIVE", {"duration", "creator_name"}),
        ),
    ],
)
def test_heterogeneous_responses_normalize_and_preserve_extensions(
    method_name: str,
    node: str,
    item: dict[str, Any],
    expected: tuple[str, str, str, set[str]],
) -> None:
    client = _client(
        lambda request: httpx.Response(
            200,
            json={"code": 0, "request_id": "request-1", "data": {node: [item]}},
        )
    )
    arguments = {
        "shop_cipher": "cipher",
        "date": "2026-08-19",
        "time_slot": "7D",
        "currency": "USD",
    }
    if method_name == "list_creators":
        arguments["author_type"] = "ALL"

    page = asyncio.run(getattr(client, method_name)("token", **arguments))
    entry = page.entries[0]

    assert (entry.entity_type, entry.external_id, entry.display_name) == expected[:3]
    assert entry.rank == item["rank"]
    assert entry.gmv.raw == item["gmv_range"]
    assert entry.gmv.currency_context == "USD"
    assert entry.gmv.computable is False
    assert set(entry.extensions) == expected[3]
    assert all(entry.extensions[key] == item[key] for key in expected[3])
    assert entry.raw_payload == item
    assert entry.raw_payload is not item
    assert page.platform_request_id == "request-1"
