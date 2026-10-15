from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from erp_api.services.tiktok_bestseller_client import HttpTikTokBestsellerClient
from erp_api.services.tiktok_transport import (
    TikTokApiError,
    TikTokRateLimitError,
    TikTokTimeoutError,
    TikTokTransport,
)


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
        )
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"code": 0, "data": []},
        {"code": 0, "data": {"products": {}}},
        {"code": 0, "data": {"products": ["invalid-item"]}},
        {
            "code": 0,
            "data": {
                "products": [{"id": "product-1", "rank": "1", "gmv_range": "$1-$2"}]
            },
        },
    ],
)
def test_response_parser_rejects_invalid_shapes(payload: dict[str, Any]) -> None:
    client = _client(lambda request: httpx.Response(200, json=payload))

    with pytest.raises(TikTokApiError) as error:
        asyncio.run(
            client.list_products(
                "token",
                shop_cipher="cipher",
                date="2026-08-19",
                time_slot="7D",
                currency="USD",
            )
        )

    assert error.value.code == "invalid_bestseller_response"


def test_platform_error_code_and_request_id_are_preserved() -> None:
    client = _client(
        lambda request: httpx.Response(
            403,
            headers={"x-tts-request-id": "request-denied"},
            json={"code": 105001, "message": "private detail"},
        )
    )

    with pytest.raises(TikTokApiError) as error:
        asyncio.run(
            client.list_videos(
                "token",
                shop_cipher="cipher",
                date="2026-08-19",
                time_slot="7D",
                currency="USD",
            )
        )

    assert error.value.code == "105001"
    assert error.value.request_id == "request-denied"
    assert error.value.upstream_status_code == 403
    assert "private detail" not in str(error.value)


def test_timeout_after_transport_retry_is_not_remapped() -> None:
    attempts = 0
    delays: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ReadTimeout("timed out", request=request)

    async def record_sleep(delay: float) -> None:
        delays.append(delay)

    client = _client(handler, max_retries=1, sleep=record_sleep)

    with pytest.raises(TikTokTimeoutError):
        asyncio.run(
            client.list_lives(
                "token",
                shop_cipher="cipher",
                date="2026-08-19",
                time_slot="1D",
                currency="LOCAL",
            )
        )

    assert attempts == 2
    assert delays == [0.25]


def test_429_after_transport_retry_keeps_retry_after_and_request_id() -> None:
    attempts = 0
    delays: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(
            429,
            headers={"Retry-After": "2", "x-tts-request-id": "request-rate"},
            json={"code": "rate_limit"},
        )

    async def record_sleep(delay: float) -> None:
        delays.append(delay)

    client = _client(handler, max_retries=1, sleep=record_sleep)

    with pytest.raises(TikTokRateLimitError) as error:
        asyncio.run(
            client.list_products(
                "token",
                shop_cipher="cipher",
                date="2026-08-19",
                time_slot="30D",
                currency="USD",
            )
        )

    assert attempts == 2
    assert delays == [2.0]
    assert error.value.retry_after_seconds == 2.0
    assert error.value.request_id == "request-rate"
    assert error.value.status_code == 429
