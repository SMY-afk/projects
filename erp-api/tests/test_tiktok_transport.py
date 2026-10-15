from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging

import httpx
import pytest

from erp_api.services.tiktok_transport import (
    TikTokApiError,
    TikTokRateLimitError,
    TikTokRequest,
    TikTokTransport,
    tiktok_request_context,
)


def test_transport_centralizes_endpoint_headers_and_request_signature() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"data": {"ok": True}})

    transport = TikTokTransport(
        base_url="https://open.example.test",
        app_key="app-key",
        app_secret="app-secret",
        timeout_seconds=3,
        http_transport=httpx.MockTransport(handler),
        clock=lambda: 1_700_000_000,
    )

    response = asyncio.run(
        transport.request(
            TikTokRequest("GET", "/shops", query={"page_size": "10", "cursor": "next"}),
            access_token="access-token",
        )
    )

    request = captured[0]
    expected_signature = hmac.new(
        b"app-secret",
        b"app-secret/shopsapp_keyapp-keycursornextpage_size10timestamp1700000000app-secret",
        hashlib.sha256,
    ).hexdigest()
    assert response == {"data": {"ok": True}}
    assert str(request.url).startswith("https://open.example.test/shops?")
    assert request.url.params["sign"] == expected_signature
    assert request.headers["x-tts-access-token"] == "access-token"
    assert request.headers["user-agent"].startswith("erp-api/")
    assert request.headers["accept"] == "application/json"


def test_transport_signs_the_exact_json_bytes_it_sends() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"data": {"ok": True}})

    transport = TikTokTransport(
        base_url="https://open.example.test",
        app_key="app-key",
        app_secret="app-secret",
        http_transport=httpx.MockTransport(handler),
        clock=lambda: 1_700_000_000,
    )

    asyncio.run(
        transport.request(
            TikTokRequest(
                "POST", "/products", json_body={"name": "Example", "active": True}
            )
        )
    )

    request = captured[0]
    expected_body = b'{"active":true,"name":"Example"}'
    expected_signature = hmac.new(
        b"app-secret",
        b"app-secret/productsapp_keyapp-keytimestamp1700000000"
        + expected_body
        + b"app-secret",
        hashlib.sha256,
    ).hexdigest()
    assert request.content == expected_body
    assert request.url.params["sign"] == expected_signature
    assert request.headers["content-type"] == "application/json"


def test_transport_logs_tenant_shop_platform_request_id_duration_and_result(
    monkeypatch,
) -> None:
    captured_logs: list[dict[str, object]] = []

    def record_log(message: str, *args, **kwargs) -> None:
        del message, args
        captured_logs.append(kwargs["extra"])

    monkeypatch.setattr(logging.getLogger("erp_api.tiktok"), "info", record_log)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"x-tts-request-id": "platform-request-1"},
            json={"data": {"ok": True}},
        )

    transport = TikTokTransport(
        base_url="https://open.example.test",
        app_key="app-key",
        app_secret="app-secret",
        http_transport=httpx.MockTransport(handler),
    )

    with tiktok_request_context(tenant_id="tenant-1", shop_id="shop-1"):
        result = asyncio.run(transport.request(TikTokRequest("GET", "/shops")))

    assert result == {"data": {"ok": True}}
    assert captured_logs == [
        {
            "event": "tiktok_request_completed",
            "tenant_id": "tenant-1",
            "shop_id": "shop-1",
            "platform_request_id": "platform-request-1",
            "duration_ms": captured_logs[0]["duration_ms"],
            "result": "success",
            "attempts": 1,
        }
    ]
    assert isinstance(captured_logs[0]["duration_ms"], float)


def test_transport_uses_body_request_id_when_response_header_is_missing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {"ok": True},
                "request_id": "body-request-1",
            },
        )

    transport = TikTokTransport(
        base_url="https://open.example.test",
        app_key="app-key",
        app_secret="app-secret",
        http_transport=httpx.MockTransport(handler),
    )

    result = asyncio.run(
        transport.request_with_metadata(TikTokRequest("GET", "/shops"))
    )

    assert result.platform_request_id == "body-request-1"


def test_transport_logs_sanitized_error_without_platform_message_or_secret(
    monkeypatch,
) -> None:
    captured_logs: list[dict[str, object]] = []

    def record_log(message: str, *args, **kwargs) -> None:
        del message, args
        captured_logs.append(kwargs["extra"])

    monkeypatch.setattr(logging.getLogger("erp_api.tiktok"), "error", record_log)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"x-tts-request-id": "platform-request-2"},
            json={"code": "private-platform-code", "message": "refresh-token-secret"},
        )

    transport = TikTokTransport(
        base_url="https://open.example.test",
        app_key="app-key",
        app_secret="app-secret",
        http_transport=httpx.MockTransport(handler),
    )

    with pytest.raises(TikTokApiError):
        asyncio.run(
            transport.request(
                TikTokRequest("GET", "/shops"),
                tenant_id="tenant-2",
                shop_id="shop-2",
            )
        )

    assert captured_logs[0]["tenant_id"] == "tenant-2"
    assert captured_logs[0]["shop_id"] == "shop-2"
    assert captured_logs[0]["platform_request_id"] == "platform-request-2"
    assert captured_logs[0]["result"] == "error"
    assert captured_logs[0]["error_code"] == "platform_api_error"
    assert "private-platform-code" not in str(captured_logs[0])
    assert "refresh-token-secret" not in str(captured_logs[0])


def test_transport_retries_get_after_429_using_retry_after() -> None:
    attempts = 0
    delays: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(
                429, headers={"Retry-After": "2"}, json={"code": "rate_limit"}
            )
        return httpx.Response(200, json={"data": {"ok": True}})

    async def record_sleep(delay: float) -> None:
        delays.append(delay)

    transport = TikTokTransport(
        base_url="https://open.example.test",
        app_key="app-key",
        app_secret="app-secret",
        max_retries=2,
        http_transport=httpx.MockTransport(handler),
        sleep=record_sleep,
    )

    result = asyncio.run(transport.request(TikTokRequest("GET", "/shops")))

    assert result == {"data": {"ok": True}}
    assert attempts == 2
    assert delays == [2.0]


def test_transport_supports_http_date_retry_after() -> None:
    attempts = 0
    delays: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(
                429,
                headers={"Retry-After": "Tue, 14 Nov 2023 22:13:25 GMT"},
                json={"code": "rate_limit"},
            )
        return httpx.Response(200, json={"data": {"ok": True}})

    async def record_sleep(delay: float) -> None:
        delays.append(delay)

    transport = TikTokTransport(
        base_url="https://open.example.test",
        app_key="app-key",
        app_secret="app-secret",
        max_retries=1,
        http_transport=httpx.MockTransport(handler),
        sleep=record_sleep,
        clock=lambda: 1_700_000_000,
    )

    asyncio.run(transport.request(TikTokRequest("GET", "/shops")))

    assert delays == [5.0]


def test_transport_does_not_retry_a_non_idempotent_token_exchange() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(
            429, headers={"Retry-After": "3"}, json={"code": "rate_limit"}
        )

    transport = TikTokTransport(
        base_url="https://auth.example.test",
        app_key="app-key",
        app_secret="app-secret",
        max_retries=3,
        http_transport=httpx.MockTransport(handler),
    )

    with pytest.raises(TikTokRateLimitError) as error:
        asyncio.run(
            transport.request(
                TikTokRequest("POST", "/token", form={"code": "one-time"})
            )
        )

    assert attempts == 1
    assert error.value.retry_after_seconds == 3


def test_transport_maps_successful_http_platform_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"code": 12019001, "message": "invalid access token"}
        )

    transport = TikTokTransport(
        base_url="https://open.example.test",
        app_key="app-key",
        app_secret="app-secret",
        http_transport=httpx.MockTransport(handler),
    )

    with pytest.raises(TikTokApiError) as error:
        asyncio.run(transport.request(TikTokRequest("GET", "/shops")))

    assert error.value.code == "12019001"
    assert error.value.status_code == 502


def test_transport_retries_idempotent_timeouts_with_bounded_backoff() -> None:
    attempts = 0
    delays: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ReadTimeout("timed out", request=request)
        return httpx.Response(200, json={"data": {"ok": True}})

    async def record_sleep(delay: float) -> None:
        delays.append(delay)

    transport = TikTokTransport(
        base_url="https://open.example.test",
        app_key="app-key",
        app_secret="app-secret",
        max_retries=1,
        retry_base_seconds=0.25,
        http_transport=httpx.MockTransport(handler),
        sleep=record_sleep,
    )

    result = asyncio.run(transport.request(TikTokRequest("GET", "/shops")))

    assert result == {"data": {"ok": True}}
    assert attempts == 2
    assert delays == [0.25]
