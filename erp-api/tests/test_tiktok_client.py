from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from erp_api.services.tiktok_client import HttpTikTokClient
from erp_api.services.tiktok_schemas import (
    parse_authorized_shops_response,
    parse_product_page_response,
)
from erp_api.services.tiktok_transport import TikTokApiError, TikTokTransport


def _client(
    auth_handler,
    api_handler=None,
    *,
    auth_max_retries: int = 2,
) -> HttpTikTokClient:
    api_handler = api_handler or (
        lambda request: httpx.Response(200, json={"data": {}})
    )
    return HttpTikTokClient(
        auth_transport=TikTokTransport(
            base_url="https://auth.example.test",
            app_key="app-key",
            app_secret="app-secret",
            max_retries=auth_max_retries,
            http_transport=httpx.MockTransport(auth_handler),
            clock=lambda: 1_700_000_000,
        ),
        api_transport=TikTokTransport(
            base_url="https://open.example.test",
            app_key="app-key",
            app_secret="app-secret",
            http_transport=httpx.MockTransport(api_handler),
            clock=lambda: 1_700_000_000,
        ),
        token_path="/api/v2/token/get",
        identity_path="/api/shops/202309/shops",
    )


def test_exchange_code_uses_unsigned_get_query_and_is_not_retried() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(503, json={"code": "temporarily_unavailable"})

    client = _client(handler, auth_max_retries=3)

    with pytest.raises(TikTokApiError):
        asyncio.run(client.exchange_code("one-time-auth-code"))

    assert len(requests) == 1
    request = requests[0]
    assert request.method == "GET"
    assert request.url.path == "/api/v2/token/get"
    assert "sign" not in request.url.params
    assert request.headers["accept"] == "application/json"
    assert request.url.params["auth_code"] == "one-time-auth-code"
    assert request.url.params["grant_type"] == "authorized_code"
    assert request.url.params["app_key"] == "app-key"
    assert request.url.params["app_secret"] == "app-secret"
    assert request.content == b""


def test_refresh_token_uses_refresh_grant_without_signature() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "data": {
                    "access_token": "new-access-token",
                    "refresh_token": "new-refresh-token",
                    "expires_in": "3600",
                    "scope": "shop.info,product.list",
                }
            },
        )

    tokens = asyncio.run(_client(handler).refresh_access_token("current-refresh-token"))

    assert tokens.access_token == "new-access-token"
    assert tokens.scopes == ["shop.info", "product.list"]
    request = requests[0]
    assert request.method == "GET"
    assert request.url.path == "/api/v2/token/refresh"
    assert "sign" not in request.url.params
    assert request.url.params["refresh_token"] == "current-refresh-token"
    assert request.url.params["grant_type"] == "refresh_token"
    assert request.content == b""


def test_token_mapping_exposes_approved_internal_fields() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "code": 0,
                "message": "success",
                "request_id": "platform-request",
                "data": {
                    "access_token": "new-access-token",
                    "refresh_token": "new-refresh-token",
                    "expires_in": 3600,
                    "granted_scopes": ["shop.info"],
                    "open_id": "platform-user-id",
                    "seller_name": "platform-seller-name",
                },
            },
        )

    tokens = asyncio.run(_client(handler).refresh_access_token("refresh-token"))

    assert tokens.__dict__ == {
        "access_token": "new-access-token",
        "refresh_token": "new-refresh-token",
        "expires_in": 3600,
        "scopes": ["shop.info"],
        "open_id": "platform-user-id",
        "user_type": None,
        "refresh_expires_in": None,
        "region": None,
    }
    assert not hasattr(tokens, "seller_name")


def test_token_mapping_converts_platform_expiry_timestamp(monkeypatch) -> None:
    monkeypatch.setattr(
        "erp_api.services.tiktok_schemas.time.time", lambda: 1_700_000_000
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": {
                    "access_token": "new-access-token",
                    "refresh_token": "new-refresh-token",
                    "access_token_expire_in": 1_700_003_600,
                    "granted_scopes": ["shop.info"],
                }
            },
        )

    tokens = asyncio.run(_client(handler).exchange_code("one-time-auth-code"))

    assert tokens.expires_in == 3600


def test_shop_identity_uses_signature_and_access_token_header() -> None:
    requests: list[httpx.Request] = []

    def auth_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"code": "unused"})

    def api_handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "data": {
                    "shop_id": "shop-001",
                    "shop_name": "Demo Shop",
                    "region": "US",
                }
            },
        )

    identity = asyncio.run(
        _client(auth_handler, api_handler).get_shop_identity("access-token")
    )

    assert identity.platform_shop_id == "shop-001"
    request = requests[0]
    assert request.url.path == "/api/shops/202309/shops"
    assert request.url.params["app_key"] == "app-key"
    assert request.url.params["timestamp"] == "1700000000"
    assert request.url.params["sign"]
    assert request.headers["x-tts-access-token"] == "access-token"


def test_shop_mapping_normalizes_nested_platform_shop_response() -> None:
    def auth_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"code": "unused"})

    def api_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "code": 0,
                "message": "success",
                "data": {
                    "shops": [
                        {
                            "id": "shop-002",
                            "name": "Demo Shop 2",
                            "seller_base_region": "US",
                            "cipher": "platform-only-cipher",
                        }
                    ],
                    "next_cursor": "platform-only-cursor",
                },
            },
        )

    identity = asyncio.run(
        _client(auth_handler, api_handler).get_shop_identity("access-token")
    )

    assert identity.__dict__ == {
        "platform_shop_id": "shop-002",
        "name": "Demo Shop 2",
        "region": "US",
        "shop_cipher": "platform-only-cipher",
    }
    assert identity.shop_cipher == "platform-only-cipher"
    assert not hasattr(identity, "next_cursor")


def test_shop_mapping_extracts_shop_cipher_without_exposing_platform_fields() -> None:
    identity = asyncio.run(
        _client(
            lambda request: httpx.Response(500),
            lambda request: httpx.Response(
                200,
                json={
                    "data": {
                        "shops": [
                            {"id": "shop-003", "region": "US", "cipher": "cipher-003"}
                        ]
                    }
                },
            ),
        ).get_shop_identity("access-token")
    )

    assert identity.shop_cipher == "cipher-003"


def test_get_authorized_shops_uses_authorization_endpoint() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "shops": [
                        {"id": "shop-005", "name": "US Shop", "cipher": "cipher-005"}
                    ]
                },
            },
        )

    shops = asyncio.run(
        _client(lambda request: httpx.Response(500), handler).get_authorized_shops(
            "access-token"
        )
    )

    assert requests[0].method == "GET"
    assert requests[0].url.path == "/authorization/202309/shops"
    assert shops[0].platform_shop_id == "shop-005"
    assert shops[0].shop_cipher == "cipher-005"


def test_authorized_shops_mapping_requires_cipher_and_normalizes_fields() -> None:
    shops = parse_authorized_shops_response(
        {
            "data": {
                "shops": [
                    {
                        "id": "shop-004",
                        "name": "US Shop",
                        "region": "US",
                        "cipher": "cipher-004",
                    }
                ]
            }
        }
    )

    assert shops[0].__dict__ == {
        "platform_shop_id": "shop-004",
        "name": "US Shop",
        "region": "US",
        "shop_cipher": "cipher-004",
    }


def test_authorized_shops_mapping_rejects_missing_cipher() -> None:
    with pytest.raises(TikTokApiError, match="ID and cipher"):
        parse_authorized_shops_response({"data": {"shops": [{"id": "shop-004"}]}})


def test_product_page_mapping_normalizes_product_and_sku_fields() -> None:
    page = parse_product_page_response(
        {
            "code": 0,
            "data": {
                "next_page_token": "next-token",
                "total_count": 36,
                "products": [
                    {
                        "id": "product-001",
                        "create_time": "1775802471",
                        "audit": {"status": "APPROVED"},
                        "sales_regions": ["US"],
                        "main_images": [
                            {"urls": ["https://cdn.example.com/product-001.jpg"]}
                        ],
                        "skus": [
                            {
                                "id": "sku-001",
                                "seller_sku": "TOY-001",
                                "price": {"sale_price": "19.99", "currency": "USD"},
                                "inventory": {"quantity": "12"},
                            }
                        ],
                    }
                ],
            },
        }
    )

    assert page.next_page_token == "next-token"
    assert page.total_count == 36
    assert page.products[0].__dict__ == {
        "platform_product_id": "product-001",
        "name": "product-001",
        "status": "APPROVED",
        "create_time": 1775802471,
        "sales_regions": ["US"],
        "skus": [page.products[0].skus[0]],
        "image_urls": ["https://cdn.example.com/product-001.jpg"],
    }
    assert page.products[0].skus[0].__dict__ == {
        "platform_sku_id": "sku-001",
        "seller_sku": "TOY-001",
        "price_amount": "19.99",
        "currency": "USD",
        "inventory_quantity": 12,
    }


def test_product_page_mapping_rejects_missing_product_id() -> None:
    with pytest.raises(TikTokApiError, match="product ID"):
        parse_product_page_response({"data": {"products": [{"skus": []}]}})


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"data": {}}, "products list"),
        ({"data": {"products": {}}}, "products list"),
        ({"data": {"products": ["not-an-object"]}}, "invalid product"),
        ({"data": {"products": [{"id": "p-1", "skus": {}}]}}, "invalid SKU list"),
        (
            {
                "data": {
                    "products": [{"id": "p-1", "skus": [{"id": "s-1"}]}],
                    "next_page_token": 1,
                }
            },
            "page token",
        ),
    ],
)
def test_product_page_mapping_rejects_malformed_responses(
    payload: object, message: str
) -> None:
    with pytest.raises(TikTokApiError, match=message):
        parse_product_page_response(payload)  # type: ignore[arg-type]


def test_product_page_mapping_accepts_nested_amount_and_inventory_list() -> None:
    page = parse_product_page_response(
        {
            "data": {
                "products": [
                    {
                        "id": "p-1",
                        "title": "Toy",
                        "status": "LIVE",
                        "sales_regions": ["US", 1],
                        "skus": [
                            {
                                "id": "s-1",
                                "price": {
                                    "sale_price": {"amount": "9.50", "currency": "USD"}
                                },
                                "inventory": [
                                    {"quantity": "2"},
                                    {"available_quantity": 3},
                                ],
                            }
                        ],
                    }
                ],
                "total_count": "1",
            }
        }
    )

    assert page.total_count == 1
    assert page.products[0].name == "Toy"
    assert page.products[0].sales_regions == ["US"]
    assert page.products[0].skus[0].price_amount == "9.50"
    assert page.products[0].skus[0].currency == "USD"
    assert page.products[0].skus[0].inventory_quantity == 5


def test_product_page_mapping_rejects_non_object_payload() -> None:
    with pytest.raises(TikTokApiError, match="not an object"):
        parse_product_page_response([])  # type: ignore[arg-type]


def test_list_products_uses_v2_search_path_and_pagination_body() -> None:
    requests: list[httpx.Request] = []

    def auth_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"code": "unused"})

    def api_handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {"products": [], "next_page_token": "next", "total_count": 36},
            },
        )

    page = asyncio.run(
        _client(auth_handler, api_handler).list_products(
            "access-token",
            shop_id="shop-001",
            shop_cipher="cipher-001",
            page_token="previous",
            page_size=50,
            search_status=1,
            seller_sku_list=["TOY-001"],
            create_time_from=100,
            create_time_to=200,
        )
    )

    request = requests[0]
    assert request.method == "POST"
    assert request.url.path == "/product/202502/products/search"
    assert request.url.params["shop_id"] == "shop-001"
    assert request.url.params["shop_cipher"] == "cipher-001"
    assert request.url.params["page_size"] == "50"
    assert request.url.params["page_token"] == "previous"
    assert request.headers["x-tts-access-token"] == "access-token"
    assert request.headers["content-type"] == "application/json"
    assert json.loads(request.content) == {
        "search_status": 1,
        "seller_sku_list": ["TOY-001"],
        "create_time_from": 100,
        "create_time_to": 200,
    }
    assert page.next_page_token == "next"
    assert page.total_count == 36


def test_list_products_rejects_invalid_page_size_before_request() -> None:
    client = _client(lambda request: httpx.Response(500, json={"code": "unused"}))

    with pytest.raises(ValueError, match="page_size"):
        asyncio.run(client.list_products("access-token", page_size=101))


def test_list_products_propagates_platform_error_without_parsing_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": 36009034, "message": "deprecated"})

    with pytest.raises(TikTokApiError) as error:
        asyncio.run(
            _client(lambda request: httpx.Response(500), handler).list_products(
                "access-token"
            )
        )

    assert error.value.code == "36009034"
    assert error.value.status_code == 502


def test_list_products_maps_invalid_success_payload_to_schema_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"code": 0, "data": {"next_page_token": "next"}}
        )

    with pytest.raises(TikTokApiError) as error:
        asyncio.run(
            _client(lambda request: httpx.Response(500), handler).list_products(
                "access-token"
            )
        )

    assert error.value.code == "invalid_product_response"
    assert error.value.status_code == 502


def test_iter_product_pages_follows_next_page_token() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        token = request.url.params.get("page_token")
        next_token = "page-2" if token is None else ""
        product_id = "product-1" if token is None else "product-2"
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "products": [{"id": product_id, "skus": []}],
                    "next_page_token": next_token,
                    "total_count": 2,
                },
            },
        )

    async def collect() -> list[str]:
        pages: list[str] = []
        async for page in _client(
            lambda request: httpx.Response(500), handler
        ).iter_product_pages("access-token", page_size=50):
            pages.append(page.products[0].platform_product_id)
        return pages

    assert asyncio.run(collect()) == ["product-1", "product-2"]
    assert [request.url.params.get("page_token") for request in requests] == [
        None,
        "page-2",
    ]


def test_iter_product_pages_can_limit_pages_without_fetching_next_page() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {"products": [], "next_page_token": "page-2", "total_count": 2},
            },
        )

    async def collect() -> int:
        count = 0
        async for _ in _client(
            lambda request: httpx.Response(500), handler
        ).iter_product_pages("access-token", max_pages=1):
            count += 1
        return count

    assert asyncio.run(collect()) == 1


def test_iter_product_pages_stops_when_reported_total_is_reached() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "products": [{"id": "product-1", "skus": []}],
                    "next_page_token": "unused-terminal-token",
                    "total_count": 1,
                },
            },
        )

    async def collect() -> list[str]:
        products = []
        async for page in _client(
            lambda request: httpx.Response(500), handler
        ).iter_product_pages("access-token"):
            products.extend(item.platform_product_id for item in page.products)
        return products

    assert asyncio.run(collect()) == ["product-1"]
    assert len(requests) == 1
    assert len(requests) == 1


def test_iter_product_pages_rejects_repeated_page_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"code": 0, "data": {"products": [], "next_page_token": "same"}},
        )

    async def consume() -> None:
        async for _ in _client(
            lambda request: httpx.Response(500), handler
        ).iter_product_pages("access-token"):
            pass

    with pytest.raises(TikTokApiError, match="repeated page token"):
        asyncio.run(consume())
