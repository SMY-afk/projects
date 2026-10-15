from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from erp_api.core.permissions import AFFILIATE_CENTER_VIEW, SYNC_TRIGGER
from erp_api.routers import affiliate_live_accounts
from erp_api.routers.auth import get_authenticated_user, require_session
from erp_api.services.analytics_read_repository import StoredAnalyticsContent
from erp_api.services.auth import AuthSession, CurrentUser


class FakeReadRepository:
    def __init__(self) -> None:
        self.calls = []

    async def shop_exists(self, tenant_id, shop_id):
        return True

    async def get_shop_timezone(self, tenant_id, shop_id):
        return "America/Los_Angeles"

    async def list_page(self, tenant_id, shop_id, **kwargs):
        self.calls.append((tenant_id, shop_id, kwargs))
        item = StoredAnalyticsContent(
            platform_external_id="live-1",
            fields={
                "accountType": "AFFILIATE_ACCOUNTS",
                "username": "creator-one",
                "gmvAmount": "128.50",
                "gmvCurrency": "USD",
            },
            source_status="ended",
            status="ended",
            source_updated_at=datetime(2026, 9, 1, tzinfo=UTC),
            observed_at=datetime(2026, 9, 2, tzinfo=UTC),
        )
        return SimpleNamespace(
            items=[item],
            total=126,
            as_of=datetime(2026, 9, 2, tzinfo=UTC),
        )


class FakeQueue:
    def __init__(self) -> None:
        self.calls = []

    async def enqueue_job(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return object()


def _client(permissions: list[str]):
    tenant_id, user_id = uuid4(), uuid4()
    app = FastAPI()
    app.include_router(affiliate_live_accounts.router, prefix="/api")
    repository = FakeReadRepository()
    app.state.affiliate_live_account_repository = repository
    app.state.arq_queue = FakeQueue()
    app.state.clock = lambda: datetime(2026, 9, 3, 18, tzinfo=UTC)
    app.dependency_overrides[require_session] = lambda: AuthSession(user_id, tenant_id)
    app.dependency_overrides[get_authenticated_user] = lambda: CurrentUser(
        user_id, "Admin", "admin", [], permissions
    )
    return TestClient(app), repository


def test_lists_only_affiliate_account_lives() -> None:
    client, repository = _client([AFFILIATE_CENTER_VIEW])

    response = client.get(
        "/api/affiliate-center/live-accounts",
        params={
            "shopId": str(uuid4()),
            "preset": "last7d",
            "page": 2,
            "pageSize": 50,
            "sortBy": "gmv",
            "sortOrder": "desc",
        },
    )

    assert response.status_code == 200
    assert response.json()["data"][0]["fields"]["accountType"] == "AFFILIATE_ACCOUNTS"
    assert response.json()["pagination"] == {
        "page": 2,
        "pageSize": 50,
        "total": 126,
    }
    assert repository.calls[0][2] == {
        "page": 2,
        "page_size": 50,
        "sort_by": "gmv",
        "sort_order": "desc",
        "account_type": "AFFILIATE_ACCOUNTS",
        "window_start": datetime(2026, 8, 28, 7, tzinfo=UTC),
        "window_end": datetime(2026, 9, 4, 7, tzinfo=UTC),
    }


def test_live_accounts_requires_affiliate_center_permission() -> None:
    client, _ = _client([])

    response = client.get(
        "/api/affiliate-center/live-accounts", params={"shopId": str(uuid4())}
    )

    assert response.status_code == 403


def test_sync_live_accounts_enqueues_only_affiliate_account_window() -> None:
    client, _ = _client([AFFILIATE_CENTER_VIEW, SYNC_TRIGGER])
    shop_id = uuid4()

    response = client.post(
        "/api/affiliate-center/live-accounts/sync",
        json={"shopId": str(shop_id), "preset": "last7d"},
    )

    assert response.status_code == 202
    assert response.json()["captureMode"] == "official_api_owned"
    assert len(response.json()["items"]) == 1
    queue = client.app.state.arq_queue
    args, kwargs = queue.calls[0]
    assert args[0] == "sync_analytics_job"
    assert args[3] == "live"
    assert kwargs["account_type"] == "AFFILIATE_ACCOUNTS"
    assert kwargs["source_kind"] == "official_api"


def test_sync_two_month_live_accounts_uses_two_bounded_windows() -> None:
    client, _ = _client([AFFILIATE_CENTER_VIEW, SYNC_TRIGGER])

    response = client.post(
        "/api/affiliate-center/live-accounts/sync",
        json={"shopId": str(uuid4()), "preset": "last60d"},
    )

    assert response.status_code == 202
    queue = client.app.state.arq_queue
    assert len(queue.calls) == 2
    windows = [
        (call[1]["window_start"], call[1]["window_end"])
        for call in queue.calls
    ]
    assert windows == [
        ("2026-07-06T07:00:00+00:00", "2026-08-05T07:00:00+00:00"),
        ("2026-08-05T07:00:00+00:00", "2026-09-04T07:00:00+00:00"),
    ]


def test_sync_live_accounts_requires_sync_permission() -> None:
    client, _ = _client([AFFILIATE_CENTER_VIEW])

    response = client.post(
        "/api/affiliate-center/live-accounts/sync",
        json={"shopId": str(uuid4()), "preset": "today"},
    )

    assert response.status_code == 403


def test_custom_live_account_range_is_used_for_reads_and_sync() -> None:
    client, repository = _client([AFFILIATE_CENTER_VIEW, SYNC_TRIGGER])
    shop_id = uuid4()
    params = {
        "shopId": str(shop_id),
        "preset": "custom",
        "customFrom": "2026-08-01",
        "customTo": "2026-08-15",
    }

    response = client.get("/api/affiliate-center/live-accounts", params=params)
    sync_response = client.post(
        "/api/affiliate-center/live-accounts/sync",
        json=params,
    )

    assert response.status_code == 200
    assert sync_response.status_code == 202
    assert repository.calls[-1][2]["window_start"] == datetime(
        2026, 8, 1, 7, tzinfo=UTC
    )
    assert repository.calls[-1][2]["window_end"] == datetime(
        2026, 8, 16, 7, tzinfo=UTC
    )
    _, kwargs = client.app.state.arq_queue.calls[-1]
    assert kwargs["window_start"] == "2026-08-01T07:00:00+00:00"
    assert kwargs["window_end"] == "2026-08-16T07:00:00+00:00"
