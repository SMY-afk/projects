from datetime import UTC, date, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from erp_api.core.permissions import AFFILIATE_CENTER_VIEW
from erp_api.routers import affiliate_local_export
from erp_api.routers.auth import get_authenticated_user, require_session
from erp_api.services.affiliate_local_export_service import TARGET_SHOPS
from erp_api.services.analytics_read_repository import StoredAnalyticsContent
from erp_api.services.auth import AuthSession, CurrentUser

SHOP_NAMES = (
    "Akeleo Toys",
    "Akeleo Fun Toys",
    "Akeleo-Drive",
    "NEOPUP",
    "fanfu toy tool",
)


def test_local_export_uses_the_confirmed_cross_border_shop_mapping() -> None:
    targets = {target.business_name: target for target in TARGET_SHOPS}

    assert targets["跨境4"].source_name == "Akeleo Fun Toys"
    assert targets["跨境4"].product_line == "遥控车"
    assert targets["跨境7"].source_name == "Akeleo-Drive"
    assert targets["跨境7"].product_line == "童车"


class FakeShopRepository:
    def __init__(self) -> None:
        self.shops = [
            {
                "id": uuid4(),
                "shopName": name,
                "timezone": "America/Los_Angeles",
                "currency": None if name == "Akeleo Fun Toys" else "USD",
            }
            for name in SHOP_NAMES
        ]

    async def list_shops(self, tenant_id):
        return self.shops


class FakeCenterRepository:
    def __init__(self, latest_dates_by_shop=None) -> None:
        self.calls = []
        self.latest_dates_by_shop = latest_dates_by_shop or {}

    async def latest_available_dates(self, tenant_id, shop_id):
        return self.latest_dates_by_shop.get(
            shop_id,
            {
                "creators": date(2026, 9, 3),
                "videos": date(2026, 9, 3),
                "liveAccounts": date(2026, 9, 3),
            },
        )

    async def list_creators(self, tenant_id, query, **kwargs):
        self.calls.append(("creators", query.shop_id, kwargs))
        return {
            "report": {"id": "report-1"},
            "items": [
                {
                    "username": f"creator-{query.shop_id}",
                    "affiliateGmvMinor": 100,
                    "avatarUrl": "must-not-be-exported",
                }
            ],
            "total": 1,
        }

    async def list_videos(self, tenant_id, query, **kwargs):
        self.calls.append(("videos", query.shop_id, kwargs))
        return {
            "run": {"runId": "run-1"},
            "items": [
                {
                    "creatorUsername": f"creator-{query.shop_id}",
                    "creatorNickname": "nickname",
                    "videoPostTime": "2026-09-01T00:00:00Z",
                    "title": "must-not-be-exported",
                }
            ],
            "total": 1,
        }


class MissingVideoSnapshotRepository(FakeCenterRepository):
    async def list_videos(self, tenant_id, query, **kwargs):
        return {"run": None, "items": [], "total": 0}


class FakeLiveRepository:
    def __init__(self) -> None:
        self.calls = []

    async def list_page(self, tenant_id, shop_id, **kwargs):
        self.calls.append((shop_id, kwargs))
        item = StoredAnalyticsContent(
            platform_external_id="live-1",
            fields={
                "username": f"creator-{shop_id}",
                "startTime": "1788220800",
                "gmvAmount": "999.00",
            },
            source_status="ended",
            status="ended",
            source_updated_at=datetime(2026, 9, 1, tzinfo=UTC),
            observed_at=datetime(2026, 9, 2, tzinfo=UTC),
        )
        return SimpleNamespace(
            items=[item],
            total=1,
            as_of=datetime(2026, 9, 2, tzinfo=UTC),
        )


def _client(permissions, *, app_env="test", client_host="testclient"):
    tenant_id, user_id = uuid4(), uuid4()
    app = FastAPI()
    app.include_router(affiliate_local_export.router, prefix="/api")
    shops = FakeShopRepository()
    latest_dates_by_shop = {
        item["id"]: {
            "creators": date(2026, 9, 2)
            if item["shopName"] == "Akeleo Toys"
            else date(2026, 9, 3),
            "videos": date(2026, 9, 2)
            if item["shopName"] == "Akeleo Toys"
            else date(2026, 9, 3),
            "liveAccounts": date(2026, 9, 2)
            if item["shopName"] == "Akeleo Toys"
            else date(2026, 9, 3),
        }
        for item in shops.shops
    }
    center = FakeCenterRepository(latest_dates_by_shop)
    live = FakeLiveRepository()
    app.state.settings = SimpleNamespace(
        app_env=app_env,
        feishu_app_id="app-id",
        feishu_app_secret=SecretStr("app-secret"),
        feishu_new_app_id="new-app-id",
        feishu_new_app_secret=SecretStr("new-app-secret"),
    )
    app.state.clock = lambda: datetime(2026, 9, 3, 18, tzinfo=UTC)
    app.state.affiliate_creator_repository = shops
    app.state.affiliate_center_read_repository = center
    app.state.affiliate_live_account_repository = live
    app.dependency_overrides[require_session] = lambda: AuthSession(user_id, tenant_id)
    app.dependency_overrides[get_authenticated_user] = lambda: CurrentUser(
        user_id, "Admin", "admin", [], permissions
    )
    return TestClient(app, client=(client_host, 50000)), shops, center, live


def test_exports_five_mapped_shops_and_only_required_fields() -> None:
    client, _, center, live = _client([AFFILIATE_CENTER_VIEW])

    response = client.get(
        "/api/affiliate-center/local-export",
        params={"from": "2026-07-03", "to": "2026-09-03"},
    )

    assert response.status_code == 200
    assert (
        "affiliate-center-2026-07-03-to-2026-09-03.json"
        in response.headers["content-disposition"]
    )
    payload = response.json()
    assert payload["source"] == "local-erp-affiliate-center"
    assert payload["window"] == {"from": "2026-07-03", "to": "2026-09-03"}
    assert [shop["shopName"] for shop in payload["shops"]] == [
        "跨境3",
        "跨境7",
        "跨境4",
        "跨境12",
        "本土店",
    ]
    assert payload["shops"][0]["sourceShopName"] == "fanfu toy tool"
    assert payload["shops"][4]["sourceShopName"] == "Akeleo Toys"
    assert payload["shops"][0]["sourceWindow"] == {
        "from": "2026-07-03",
        "to": "2026-09-03",
    }
    assert payload["shops"][4]["sourceWindow"] == {
        "from": "2026-07-02",
        "to": "2026-09-02",
    }
    assert payload["shops"][1]["currency"] == "USD"
    assert payload["shops"][0]["totals"] == {
        "creators": 1,
        "videos": 1,
        "liveAccounts": 1,
    }
    assert set(payload["shops"][0]["creators"][0]) == {
        "username",
        "affiliateGmvMinor",
    }
    assert set(payload["shops"][0]["videos"][0]) == {
        "creatorUsername",
        "creatorNickname",
        "videoPostTime",
    }
    assert payload["shops"][0]["liveAccounts"][0]["fields"] == {
        "username": f"creator-{payload['shops'][0]['shopId']}",
        "startTime": "1788220800",
    }
    assert len(center.calls) == 10
    assert len(live.calls) == 5


def test_export_uses_each_shops_latest_resource_cutoff() -> None:
    client, shops, center, _ = _client([AFFILIATE_CENTER_VIEW])
    fanfu = next(item for item in shops.shops if item["shopName"] == "fanfu toy tool")
    center.latest_dates_by_shop[fanfu["id"]] = {
        "creators": date(2026, 9, 1),
        "videos": date(2026, 8, 31),
        "liveAccounts": date(2026, 8, 30),
    }

    response = client.get(
        "/api/affiliate-center/local-export",
        params={"from": "2026-07-05", "to": "2026-09-02"},
    )

    assert response.status_code == 200
    fanfu_export = response.json()["shops"][0]
    akeleo_export = response.json()["shops"][1]
    assert fanfu_export["sourceWindow"] == {
        "from": "2026-07-04",
        "to": "2026-09-01",
    }
    assert fanfu_export["sourceWindows"] == {
        "creators": {"from": "2026-07-04", "to": "2026-09-01"},
        "videos": {"from": "2026-07-03", "to": "2026-08-31"},
        "liveAccounts": {"from": "2026-07-02", "to": "2026-08-30"},
    }
    assert akeleo_export["sourceWindows"] == {
        "creators": {"from": "2026-07-05", "to": "2026-09-02"},
        "videos": {"from": "2026-07-05", "to": "2026-09-02"},
        "liveAccounts": {"from": "2026-07-05", "to": "2026-09-02"},
    }


@pytest.mark.parametrize("missing", ["videos", "liveAccounts"])
def test_export_fails_closed_when_any_shop_lacks_a_latest_date(missing) -> None:
    client, shops, center, _ = _client([AFFILIATE_CENTER_VIEW])
    neopup = next(item for item in shops.shops if item["shopName"] == "NEOPUP")
    center.latest_dates_by_shop[neopup["id"]].pop(missing)

    response = client.get(
        "/api/affiliate-center/local-export",
        params={"from": "2026-07-05", "to": "2026-09-02"},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "affiliate_snapshot_incomplete"
    assert response.json()["shop"] == "跨境12"
    assert response.json()["resource"] == missing


def test_export_requires_affiliate_view_permission() -> None:
    client, *_ = _client([])

    response = client.get(
        "/api/affiliate-center/local-export",
        params={"from": "2026-07-03", "to": "2026-09-03"},
    )

    assert response.status_code == 403


def test_export_is_disabled_in_production() -> None:
    client, *_ = _client([AFFILIATE_CENTER_VIEW], app_env="production")

    response = client.get(
        "/api/affiliate-center/local-export",
        params={"from": "2026-07-03", "to": "2026-09-03"},
    )

    assert response.status_code == 404


def test_export_rejects_non_loopback_clients_in_development() -> None:
    client, *_ = _client(
        [AFFILIATE_CENTER_VIEW], app_env="development", client_host="192.0.2.1"
    )

    response = client.get(
        "/api/affiliate-center/local-export",
        params={"from": "2026-07-03", "to": "2026-09-03"},
    )

    assert response.status_code == 403


def test_export_allows_loopback_clients_in_development() -> None:
    client, *_ = _client(
        [AFFILIATE_CENTER_VIEW], app_env="development", client_host="127.0.0.1"
    )

    response = client.get(
        "/api/affiliate-center/local-export",
        params={"from": "2026-07-03", "to": "2026-09-03"},
    )

    assert response.status_code == 200


def test_export_rejects_an_overlong_window() -> None:
    client, *_ = _client([AFFILIATE_CENTER_VIEW])

    response = client.get(
        "/api/affiliate-center/local-export",
        params={"from": "2026-01-01", "to": "2026-09-03"},
    )

    assert response.status_code == 422


def test_export_rejects_missing_complete_snapshots() -> None:
    client, *_ = _client([AFFILIATE_CENTER_VIEW])
    client.app.state.affiliate_center_read_repository = MissingVideoSnapshotRepository()

    response = client.get(
        "/api/affiliate-center/local-export",
        params={"from": "2026-07-03", "to": "2026-09-03"},
    )

    assert response.status_code == 409
    assert response.json() == {
        "code": "affiliate_snapshot_incomplete",
        "message": (
            "跨境3的视频数据不完整：2026-07-03 至 2026-09-03 没有可用的完整快照。"
        ),
        "shop": "跨境3",
        "resource": "videos",
        "window": {"from": "2026-07-03", "to": "2026-09-03"},
        "missingDates": [],
    }


def test_feishu_export_requires_affiliate_view_permission() -> None:
    client, *_ = _client([])

    response = client.get("/api/affiliate-center/feishu-export")

    assert response.status_code == 403


def test_feishu_export_is_disabled_in_production() -> None:
    client, *_ = _client([AFFILIATE_CENTER_VIEW], app_env="production")

    response = client.get("/api/affiliate-center/feishu-export")

    assert response.status_code == 404


def test_feishu_export_rejects_missing_configuration() -> None:
    client, *_ = _client([AFFILIATE_CENTER_VIEW])
    client.app.state.settings.feishu_new_app_secret = None

    response = client.get("/api/affiliate-center/feishu-export")

    assert response.status_code == 503


def test_feishu_export_downloads_normalized_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_export(app_id: str, app_secret: str):
        assert app_id == "new-app-id"
        assert app_secret == "new-app-secret"
        return {
            "source": "feishu-bitable-readonly",
            "tables": [
                {"productLine": "童车", "total": 0, "rows": []},
                {"productLine": "遥控车", "total": 0, "rows": []},
            ],
            "warnings": [],
        }

    monkeypatch.setattr(
        affiliate_local_export, "build_feishu_creator_export", fake_export
    )
    client, *_ = _client([AFFILIATE_CENTER_VIEW])

    response = client.get("/api/affiliate-center/feishu-export")

    assert response.status_code == 200
    assert response.headers["content-disposition"] == (
        'attachment; filename="feishu-creators.json"'
    )
    assert [table["productLine"] for table in response.json()["tables"]] == [
        "童车",
        "遥控车",
    ]
