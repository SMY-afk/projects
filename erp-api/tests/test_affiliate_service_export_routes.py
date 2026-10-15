from datetime import UTC, date, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from erp_api.routers import affiliate_service_export
from tests.test_affiliate_local_export_routes import (
    FakeCenterRepository,
    FakeLiveRepository,
    FakeShopRepository,
)

SERVICE_TOKEN = "service-token-with-at-least-32-characters"


def _client(token: str | None = SERVICE_TOKEN) -> TestClient:
    tenant_id = uuid4()
    app = FastAPI()
    app.include_router(affiliate_service_export.router, prefix="/api")
    app.state.settings = SimpleNamespace(
        affiliate_export_service_token=SecretStr(token) if token else None,
        affiliate_export_tenant_id=tenant_id,
        feishu_app_id="app-id",
        feishu_app_secret=SecretStr("app-secret"),
        feishu_new_app_id="new-app-id",
        feishu_new_app_secret=SecretStr("new-app-secret"),
    )
    app.state.clock = lambda: datetime(2026, 9, 4, 8, tzinfo=UTC)
    app.state.affiliate_creator_repository = FakeShopRepository()
    app.state.affiliate_center_read_repository = FakeCenterRepository()
    app.state.affiliate_live_account_repository = FakeLiveRepository()
    return TestClient(app)


def test_internal_export_requires_matching_service_token() -> None:
    client = _client()

    missing = client.get("/api/internal/affiliate-center/feishu-export")
    invalid = client.get(
        "/api/internal/affiliate-center/feishu-export",
        headers={"x-erp-service-token": "wrong"},
    )

    assert missing.status_code == 401
    assert invalid.status_code == 401


def test_internal_local_export_uses_bound_tenant_and_skill_mapping() -> None:
    response = _client().get(
        "/api/internal/affiliate-center/local-export",
        params={"from": "2026-07-04", "to": "2026-09-04"},
        headers={"x-erp-service-token": SERVICE_TOKEN},
    )

    assert response.status_code == 200
    shops = response.json()["shops"]
    assert [(shop["shopName"], shop["productLine"]) for shop in shops] == [
        ("跨境3", "童车"),
        ("跨境7", "童车"),
        ("跨境4", "遥控车"),
        ("跨境12", "遥控车"),
        ("本土店", "遥控车"),
    ]


def test_internal_local_export_can_target_one_shop() -> None:
    client = _client()
    response = client.get(
        "/api/internal/affiliate-center/local-export",
        params={"from": "2026-07-04", "to": "2026-09-04", "shop": "跨境7"},
        headers={"x-erp-service-token": SERVICE_TOKEN},
    )
    assert response.status_code == 200
    assert [shop["shopName"] for shop in response.json()["shops"]] == ["跨境7"]
    invalid = client.get(
        "/api/internal/affiliate-center/local-export",
        params={"from": "2026-07-04", "to": "2026-09-04", "shop": "unknown"},
        headers={"x-erp-service-token": SERVICE_TOKEN},
    )
    assert invalid.status_code == 422


def test_internal_feishu_export_uses_server_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_export(app_id: str, app_secret: str):
        assert (app_id, app_secret) == ("new-app-id", "new-app-secret")
        return {
            "source": "feishu-bitable-readonly",
            "tables": [
                {"productLine": "童车", "total": 0, "rows": []},
                {"productLine": "遥控车", "total": 0, "rows": []},
            ],
            "warnings": [],
        }

    monkeypatch.setattr(
        affiliate_service_export, "build_feishu_creator_export", fake_export
    )
    response = _client().get(
        "/api/internal/affiliate-center/feishu-export",
        headers={"x-erp-service-token": SERVICE_TOKEN},
    )

    assert response.status_code == 200
    assert response.json()["source"] == "feishu-bitable-readonly"


@pytest.mark.asyncio
async def test_local_export_coalesces_repeated_identical_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []
    tenant_id = uuid4()
    window_start = date(2026, 8, 6)
    window_end = date(2026, 10, 6)
    targets = affiliate_service_export.TARGET_SHOPS[:1]

    async def fake_export(*args, **kwargs):
        calls.append((args, kwargs))
        return {"source": "local-erp-affiliate-center", "shops": []}

    monkeypatch.setattr(
        affiliate_service_export, "build_affiliate_local_export", fake_export
    )
    affiliate_service_export._local_export_cache.clear()
    kwargs = {
        "now": datetime(2026, 10, 8, 5, tzinfo=UTC),
        "shop_repository": object(),
        "center_repository": object(),
        "live_repository": object(),
        "targets": targets,
    }
    first, second = await __import__("asyncio").gather(
        affiliate_service_export._cached_affiliate_local_export(
            tenant_id, window_start, window_end, **kwargs
        ),
        affiliate_service_export._cached_affiliate_local_export(
            tenant_id, window_start, window_end, **kwargs
        ),
    )

    assert first is second
    assert len(calls) == 1
