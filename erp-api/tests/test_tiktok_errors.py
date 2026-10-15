from fastapi import FastAPI
from fastapi.testclient import TestClient

from erp_api.core.errors import register_exception_handlers
from erp_api.services.tiktok_transport import (
    TikTokApiError,
    TikTokClientError,
    TikTokRateLimitError,
    TikTokTimeoutError,
    TikTokTransport,
)


def _client_for(error: Exception) -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/fail")
    async def fail() -> None:
        raise error

    return TestClient(app)


def test_rate_limit_error_maps_to_safe_429_response() -> None:
    error = TikTokRateLimitError(
        retry_after_seconds=7.9, request_id="platform-request-secret"
    )

    response = _client_for(error).get(
        "/fail", headers={"X-Request-ID": "internal-request-id"}
    )

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "8"
    assert response.json()["code"] == "upstream_rate_limited"
    assert "platform-request-secret" not in response.text


def test_timeout_error_maps_to_safe_504_response() -> None:
    response = _client_for(TikTokTimeoutError("access-token-sensitive-value")).get(
        "/fail"
    )

    assert response.status_code == 504
    assert response.json()["code"] == "upstream_timeout"
    assert "access-token-sensitive-value" not in response.text


def test_platform_error_maps_to_safe_502_response() -> None:
    error = TikTokApiError(
        "platform response included refresh-token-sensitive-value",
        code="platform_private_code",
        status_code=400,
        request_id="platform-private-request-id",
    )

    response = _client_for(error).get("/fail")

    assert response.status_code == 502
    assert response.json()["code"] == "upstream_error"
    assert "platform_private_code" not in response.text
    assert "refresh-token-sensitive-value" not in response.text
    assert "platform-private-request-id" not in response.text


def test_transport_error_maps_to_safe_502_response() -> None:
    response = _client_for(TikTokClientError("access-token-sensitive-value")).get(
        "/fail"
    )

    assert response.status_code == 502
    assert response.json()["code"] == "upstream_error"
    assert "access-token-sensitive-value" not in response.text


def test_transport_classifies_allowlisted_platform_error_codes() -> None:
    error = TikTokApiError(
        "sensitive platform response",
        code="36004004",
        status_code=502,
    )

    assert TikTokTransport._safe_error_code(error) == "invalid_auth_code"


def test_transport_does_not_log_unknown_platform_error_codes() -> None:
    error = TikTokApiError(
        "sensitive platform response",
        code="private-platform-code",
        status_code=502,
    )

    assert TikTokTransport._safe_error_code(error) == "platform_api_error"
