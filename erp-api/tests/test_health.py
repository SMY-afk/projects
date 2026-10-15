import asyncio
from types import SimpleNamespace

from fastapi import Response
from fastapi.testclient import TestClient

from erp_api.infrastructure.database import Database
from erp_api.main import app
from erp_api.routers.health import _sample_sync_config_status, readiness

client = TestClient(app)


def test_api_health_returns_service_status_and_request_id() -> None:
    response = client.get("/api/health", headers={"X-Request-ID": "health-test-001"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "health-test-001"
    assert response.json()["status"] == "ok"
    assert response.json()["service"] == "ERP API"


def test_lifespan_exposes_the_shared_database() -> None:
    with TestClient(app) as lifespan_client:
        assert isinstance(lifespan_client.app.state.database, Database)


def test_liveness_is_available_without_dependencies() -> None:
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "dependencies": {}}


def test_openapi_exposes_readiness_check() -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert "/readyz" in response.json()["paths"]
    assert "/api/health" in response.json()["paths"]


def test_readiness_reports_unavailable_dependencies(monkeypatch) -> None:
    async def unavailable_dependencies(_database, _redis_url, **_kwargs):
        return {"database": "unavailable", "redis": "unavailable"}

    monkeypatch.setattr(
        "erp_api.routers.health.probe_dependencies",
        unavailable_dependencies,
    )

    response = client.get("/readyz")

    assert response.status_code == 503
    assert response.json()["status"] == "degraded"


def test_disabled_sample_sync_does_not_make_erp_unready(monkeypatch) -> None:
    async def available_dependencies(_database, _redis_url, **kwargs):
        assert kwargs["sample_sync_enabled"] is False
        return {
            "database": "ok",
            "redis": "ok",
            "sample_sync_config": "disabled",
            "sample_schema": "disabled",
            "sample_worker": "disabled",
        }

    monkeypatch.setattr(
        "erp_api.routers.health.probe_dependencies",
        available_dependencies,
    )
    settings = _sample_settings(enabled=False)
    response = Response()
    result = asyncio.run(
        readiness(
            SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(database=object()))),
            response,
            settings,
        )
    )

    assert response.status_code == 200
    assert result.status == "ok"
    assert result.dependencies["sample_worker"] == "disabled"


def test_enabled_sample_sync_requires_schema_and_worker_not_history(monkeypatch) -> None:
    async def current_dependencies(_database, _redis_url, **kwargs):
        assert kwargs["sample_sync_enabled"] is True
        return {
            "database": "ok",
            "redis": "ok",
            "sample_sync_config": "ok",
            "sample_schema": "ok",
            "sample_worker": "unavailable",
        }

    monkeypatch.setattr(
        "erp_api.routers.health.probe_dependencies",
        current_dependencies,
    )
    response = Response()
    result = asyncio.run(
        readiness(
            SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(database=object()))),
            response,
            _sample_settings(enabled=True),
        )
    )

    assert response.status_code == 503
    assert result.status == "degraded"
    assert "sample_sync_history" not in result.dependencies


def test_partial_sample_runtime_configuration_is_unavailable() -> None:
    settings = _sample_settings(enabled=False)
    settings.feishu_sample_base_token = "configured"

    assert _sample_sync_config_status(settings) == "unavailable"


def test_cors_preflight_is_limited_to_configured_origin() -> None:
    response = client.options(
        "/api/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert response.headers["X-Request-ID"]


def test_http_errors_use_the_standard_response_shape() -> None:
    response = client.get(
        "/api/does-not-exist", headers={"X-Request-ID": "missing-001"}
    )

    assert response.status_code == 404
    assert response.headers["X-Request-ID"] == "missing-001"
    assert response.json() == {
        "code": "not_found",
        "message": "Resource not found.",
        "requestId": "missing-001",
    }


def _sample_settings(*, enabled: bool):
    value = "configured" if enabled else None
    return SimpleNamespace(
        redis_url="redis://example.invalid",
        feishu_app_id=value,
        feishu_app_secret=value,
        feishu_sample_base_token=value,
        feishu_sample_table_id=value,
        tiktok_app_key=value,
        tiktok_app_secret=value,
        tiktok_token_url=value,
        tiktok_shop_identity_url=value,
        tiktok_token_encryption_key=value,
    )
