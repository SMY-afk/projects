from __future__ import annotations

import asyncio

import httpx
import pytest

from erp_api.services.tiktok_data_client import (
    HttpTikTokAnalyticsClient,
    TikTokAnalyticsEndpoint,
)
from erp_api.services.tiktok_data_schemas import classify_analytics_failure
from erp_api.services.tiktok_transport import TikTokApiError, TikTokTransport


def _endpoint(
    path: str,
    *,
    items_path: str,
    field_map: dict[str, str],
    empty_data_as_empty_page: bool = False,
) -> TikTokAnalyticsEndpoint:
    return TikTokAnalyticsEndpoint(
        path=path,
        items_path=items_path,
        next_page_token_path="next_page_token",
        field_map=field_map,
        empty_data_as_empty_page=empty_data_as_empty_page,
    )


def _client(handler, *, sleep=asyncio.sleep) -> HttpTikTokAnalyticsClient:
    transport = TikTokTransport(
        base_url="https://open.example.test",
        app_key="app-key",
        app_secret="app-secret",
        max_retries=1,
        http_transport=httpx.MockTransport(handler),
        sleep=sleep,
        clock=lambda: 1_700_000_000,
    )
    return HttpTikTokAnalyticsClient(
        video_transport=transport,
        live_transport=transport,
        video_endpoint=_endpoint(
            "/analytics/202605/shop_videos/performance",
            items_path="videos",
            field_map={
                "videoId": "id",
                "views": "traffic.views",
                "gmv": "sales.gmv.amount",
            },
        ),
        live_endpoint=_endpoint(
            "/analytics/202509/shop_lives/performance",
            items_path="live_stream_sessions",
            field_map={"liveId": "id", "customers": "sales.customers"},
            empty_data_as_empty_page=True,
        ),
    )


def test_video_client_uses_injected_endpoint_mapping_and_transport_retry() -> None:
    requests: list[httpx.Request] = []
    delays: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(
                429, headers={"Retry-After": "1"}, json={"code": "rate_limit"}
            )
        return httpx.Response(
            200,
            json={
                "data": {
                    "videos": [
                        {
                            "id": "video-1",
                            "traffic": {"views": 42},
                            "sales": {"gmv": {"amount": "12.34"}},
                        }
                    ],
                    "next_page_token": "next-video-page",
                }
            },
        )

    async def record_sleep(delay: float) -> None:
        delays.append(delay)

    page = asyncio.run(
        _client(handler, sleep=record_sleep).list_videos(
            "access-token",
            shop_cipher="shop-cipher",
            start_date_ge="2026-08-01",
            end_date_lt="2026-08-02",
            page_size=1,
            currency="USD",
        )
    )

    assert len(requests) == 2
    assert delays == [1]
    assert requests[-1].url.path == "/analytics/202605/shop_videos/performance"
    assert requests[-1].url.params["shop_cipher"] == "shop-cipher"
    assert requests[-1].url.params["app_key"] == "app-key"
    assert requests[-1].url.params["sign"]
    assert requests[-1].headers["x-tts-access-token"] == "access-token"
    assert page.items[0].fields == {"videoId": "video-1", "views": 42, "gmv": "12.34"}
    assert page.next_page_token == "next-video-page"


def test_live_client_uses_its_own_injected_endpoint_and_mapping() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "data": {
                    "live_stream_sessions": [
                        {"id": "live-1", "sales": {"customers": 7}}
                    ],
                    "next_page_token": "",
                }
            },
        )

    page = asyncio.run(
        _client(handler).list_lives(
            "access-token",
            shop_cipher="shop-cipher",
            start_date_ge="2026-08-01",
            end_date_lt="2026-08-02",
            page_token="previous-page",
            account_type="OFFICIAL_ACCOUNTS",
        )
    )

    assert requests[0].url.path == "/analytics/202509/shop_lives/performance"
    assert requests[0].url.params["page_token"] == "previous-page"
    assert requests[0].url.params["account_type"] == "OFFICIAL_ACCOUNTS"
    assert page.items[0].fields == {"liveId": "live-1", "customers": 7}
    assert page.next_page_token == ""


def test_live_client_treats_successful_empty_data_object_as_an_empty_page() -> None:
    page = asyncio.run(
        _client(lambda request: httpx.Response(200, json={"code": 0, "data": {}}))
        .list_lives(
            "access-token",
            shop_cipher="shop-cipher",
            start_date_ge="2026-09-03",
            end_date_lt="2026-09-07",
            account_type="AFFILIATE_ACCOUNTS",
        )
    )

    assert page.items == []
    assert page.next_page_token is None
    assert page.raw_payload == {"code": 0, "data": {}}


def test_analytics_client_rejects_invalid_requests_and_unmappable_responses() -> None:
    client = _client(lambda request: httpx.Response(200, json={"data": {"videos": {}}}))

    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        asyncio.run(
            client.list_videos(
                "access-token",
                shop_cipher="shop-cipher",
                start_date_ge="2026/08/01",
                end_date_lt="2026-08-02",
            )
        )
    with pytest.raises(TikTokApiError, match="items list"):
        asyncio.run(
            client.list_videos(
                "access-token",
                shop_cipher="shop-cipher",
                start_date_ge="2026-08-01",
                end_date_lt="2026-08-02",
            )
        )
    with pytest.raises(ValueError, match="maximum window"):
        asyncio.run(
            client.list_videos(
                "access-token",
                shop_cipher="shop-cipher",
                start_date_ge="2026-08-01",
                end_date_lt="2026-09-01",
            )
        )


def test_analytics_client_rejects_repeated_cursors_without_detail_requests() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "data": {
                    "videos": [{"id": "video-1", "traffic": {}, "sales": {}}],
                    "next_page_token": "repeat",
                }
            },
        )

    async def consume() -> None:
        async for _ in _client(handler).iter_videos(
            "access-token",
            shop_cipher="shop-cipher",
            start_date_ge="2026-08-01",
            end_date_lt="2026-08-02",
        ):
            pass

    with pytest.raises(TikTokApiError, match="repeated page token"):
        asyncio.run(consume())

    assert len(requests) == 2
    assert {request.url.path for request in requests} == {
        "/analytics/202605/shop_videos/performance"
    }


@pytest.mark.parametrize("status_code", [401, 403])
def test_analytics_client_classifies_authorization_failures_without_exposing_platform_detail(
    status_code: int,
) -> None:
    client = _client(
        lambda request: httpx.Response(
            status_code,
            json={"code": status_code, "message": "platform-private-detail"},
        )
    )

    with pytest.raises(TikTokApiError) as error:
        asyncio.run(
            client.list_videos(
                "access-token",
                shop_cipher="shop-cipher",
                start_date_ge="2026-08-01",
                end_date_lt="2026-08-02",
            )
        )

    assert error.value.code == str(status_code)
    assert "platform-private-detail" not in str(error.value)
    assert classify_analytics_failure(error.value).category == "platform_error"


def test_analytics_client_preserves_a_platform_empty_list_as_empty_data() -> None:
    page = asyncio.run(
        _client(
            lambda request: httpx.Response(
                200, json={"data": {"videos": [], "next_page_token": ""}}
            )
        ).list_videos(
            "access-token",
            shop_cipher="shop-cipher",
            start_date_ge="2026-08-01",
            end_date_lt="2026-08-02",
        )
    )

    assert page.items == []
    assert page.next_page_token == ""
