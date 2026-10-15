from __future__ import annotations

import asyncio
import hashlib
import hmac
import json

import httpx
import pytest

from erp_api.services.tiktok_sample_application_client import (
    HttpTikTokSampleApplicationClient,
)
from erp_api.services.tiktok_transport import (
    TikTokApiError,
    TikTokRequest,
    TikTokResponse,
    TikTokTransport,
)


def _application(application_id: str) -> dict[str, object]:
    return {
        "id": application_id,
        "status": "PENDING",
        "creator": {},
        "product": {},
    }


class FakeTransport:
    def __init__(self, responses: list[TikTokResponse]) -> None:
        self.responses = iter(responses)
        self.calls: list[tuple[TikTokRequest, dict[str, str | None]]] = []

    async def request_with_metadata(
        self,
        request: TikTokRequest,
        *,
        access_token: str | None = None,
        tenant_id: str | None = None,
        shop_id: str | None = None,
    ) -> TikTokResponse:
        self.calls.append(
            (
                request,
                {
                    "access_token": access_token,
                    "tenant_id": tenant_id,
                    "shop_id": shop_id,
                },
            )
        )
        return next(self.responses)


def _response(
    applications: list[dict[str, object]],
    *,
    next_page_token: str | None,
    total_count: int | None,
) -> TikTokResponse:
    data: dict[str, object] = {"sample_applications": applications}
    if next_page_token is not None:
        data["next_page_token"] = next_page_token
    if total_count is not None:
        data["total_count"] = total_count
    return TikTokResponse(
        payload={"data": data},
        platform_request_id="request-1",
        status_code=200,
    )


async def _collect_pages(
    client: HttpTikTokSampleApplicationClient,
) -> list[object]:
    pages: list[object] = []
    async for page in client.iter_pages(
        "access-token",
        shop_cipher="shop-cipher",
        tenant_id="tenant-1",
        shop_id="shop-1",
        page_size=1,
    ):
        pages.append(page)
    return pages


def test_search_page_uses_202508_path_and_read_retry_policy() -> None:
    transport = FakeTransport(
        [_response([_application("one")], next_page_token=None, total_count=1)]
    )
    client = HttpTikTokSampleApplicationClient(transport)  # type: ignore[arg-type]

    page = asyncio.run(
        client.search_page(
            "access-token",
            shop_cipher="shop-cipher",
            tenant_id="tenant-1",
            shop_id="shop-1",
            page_size=1,
            status="PENDING",
        )
    )

    request, context = transport.calls[0]
    assert len(page.applications) == 1
    assert request.method == "POST"
    assert request.path == "/affiliate_seller/202508/sample_applications/search"
    assert request.query == {"shop_cipher": "shop-cipher", "page_size": "1"}
    assert request.json_body == {"status": "PENDING"}
    assert request.retryable is True
    assert context == {
        "access_token": "access-token",
        "tenant_id": "tenant-1",
        "shop_id": "shop-1",
    }


def test_search_page_uses_shared_transport_signature_and_exact_json_body() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            json={
                "data": {
                    "sample_applications": [],
                    "total_count": 0,
                }
            },
            headers={"x-tts-request-id": "sample-request-1"},
        )

    transport = TikTokTransport(
        base_url="https://open.example.test",
        app_key="app-key",
        app_secret="app-secret",
        http_transport=httpx.MockTransport(handler),
        clock=lambda: 1_700_000_000,
    )
    client = HttpTikTokSampleApplicationClient(transport)

    page = asyncio.run(
        client.search_page(
            "access-token",
            shop_cipher="shop-cipher",
            tenant_id="tenant-1",
            shop_id="shop-1",
            page_size=1,
            status="PENDING",
        )
    )

    request = captured[0]
    body = json.dumps(
        {"status": "PENDING"},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    signing_value = (
        b"app-secret"
        b"/affiliate_seller/202508/sample_applications/search"
        b"app_keyapp-keypage_size1shop_ciphershop-ciphertimestamp1700000000"
        + body
        + b"app-secret"
    )
    expected_signature = hmac.new(
        b"app-secret", signing_value, hashlib.sha256
    ).hexdigest()

    assert page.platform_request_id == "sample-request-1"
    assert request.method == "POST"
    assert request.content == body
    assert request.url.params["sign"] == expected_signature
    assert request.headers["x-tts-access-token"] == "access-token"


def test_iter_pages_follows_next_token_and_validates_total() -> None:
    transport = FakeTransport(
        [
            _response([_application("one")], next_page_token="next-1", total_count=2),
            _response([_application("two")], next_page_token=None, total_count=2),
        ]
    )
    client = HttpTikTokSampleApplicationClient(transport)  # type: ignore[arg-type]

    pages = asyncio.run(_collect_pages(client))

    assert len(pages) == 2
    assert transport.calls[0][0].query.get("page_token") is None
    assert transport.calls[1][0].query["page_token"] == "next-1"


def test_iter_pages_rejects_repeated_token() -> None:
    transport = FakeTransport(
        [
            _response([_application("one")], next_page_token="same", total_count=None),
            _response([_application("two")], next_page_token="same", total_count=None),
        ]
    )
    client = HttpTikTokSampleApplicationClient(transport)  # type: ignore[arg-type]

    with pytest.raises(TikTokApiError) as captured:
        asyncio.run(_collect_pages(client))

    assert captured.value.code == "pagination_loop"


def test_iter_pages_rejects_terminal_total_mismatch() -> None:
    transport = FakeTransport(
        [_response([_application("one")], next_page_token=None, total_count=2)]
    )
    client = HttpTikTokSampleApplicationClient(transport)  # type: ignore[arg-type]

    with pytest.raises(TikTokApiError) as captured:
        asyncio.run(_collect_pages(client))

    assert captured.value.code == "pagination_incomplete"


def test_search_page_rejects_invalid_page_size() -> None:
    client = HttpTikTokSampleApplicationClient(FakeTransport([]))  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="between 1 and 50"):
        asyncio.run(
            client.search_page(
                "access-token",
                shop_cipher="shop-cipher",
                tenant_id="tenant-1",
                shop_id="shop-1",
                page_size=51,
            )
        )


def test_creator_performance_uses_official_detail_path_and_cache() -> None:
    response = TikTokResponse(
        payload={
            "data": {
                "creator": {
                    "post_rate": "5171",
                    "avg_ec_video_play_count": 1200,
                    "units_sold": 614,
                    "pps": "4.0",
                    "pps_band": "MEDIUM",
                    "rating": "5.0",
                    "rating_count": 4,
                    "sample_score": {"overall": "86"},
                    "follower_demographics": {"gender": {"Female": "73.61"}},
                    "access_token": "must-not-be-retained",
                }
            }
        },
        platform_request_id="performance-request-1",
        status_code=200,
    )
    transport = FakeTransport([response])
    client = HttpTikTokSampleApplicationClient(transport)  # type: ignore[arg-type]

    async def fetch_twice():
        first = await client.get_creator_performance(
            "access-token",
            creator_open_id="creator-1",
            shop_cipher="shop-cipher",
            tenant_id="tenant-1",
            shop_id="shop-1",
        )
        second = await client.get_creator_performance(
            "access-token",
            creator_open_id="creator-1",
            shop_cipher="shop-cipher",
            tenant_id="tenant-1",
            shop_id="shop-1",
        )
        return first, second

    first, second = asyncio.run(fetch_twice())

    assert first.fields == second.fields
    assert first.fields["post_rate"] == "5171"
    assert first.fields["units_sold"] == 614
    assert first.fields["rating_count"] == 4
    assert first.fields["sample_score"] == {"overall": "86"}
    assert "access_token" not in first.fields
    assert first.cache_hit is False
    assert second.cache_hit is True
    assert len(transport.calls) == 1
    request, _context = transport.calls[0]
    assert request.method == "GET"
    assert request.path == "/affiliate_seller/202508/marketplace_creators/creator-1"
    assert request.query == {"shop_cipher": "shop-cipher"}
