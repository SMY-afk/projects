import json
from datetime import date
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from erp_api.core.permissions import AFFILIATE_CENTER_VIEW, SYNC_TRIGGER
from erp_api.routers import affiliate_center_stable
from erp_api.routers.auth import get_authenticated_user, require_session
from erp_api.services.affiliate_capture_intent_repository import (
    AffiliateCaptureIntentReceipt,
)
from erp_api.services.auth import AuthSession, CurrentUser


class FakeReadRepository:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    async def get_shop_context(self, tenant_id, shop_id):
        self.calls.append(("shop", tenant_id, shop_id))
        return {"shopTimezone": "America/Los_Angeles", "currency": "USD"}

    async def list_creators(self, tenant_id, query, *, page, page_size, sort, order):
        self.calls.append(("creators", tenant_id, query, page, page_size, sort, order))
        return {
            "report": None,
            "items": [],
            "page": page,
            "pageSize": page_size,
            "total": 0,
            "sort": sort,
            "order": order,
        }

    async def list_videos(
        self,
        tenant_id,
        query,
        *,
        page,
        page_size,
        sort,
        order,
        creator_open_id,
    ):
        self.calls.append(
            (
                "videos",
                tenant_id,
                query,
                page,
                page_size,
                sort,
                order,
                creator_open_id,
            )
        )
        return {
            "run": None,
            "query": query.canonical_dimensions(),
            "items": [],
            "page": page,
            "pageSize": page_size,
            "total": 0,
            "sort": sort,
            "order": order,
        }

    async def sync_status(self, tenant_id, shop_id):
        self.calls.append(("status", tenant_id, shop_id))
        return [{"resource": "creators", "status": "never_synced"}]

    async def latest_available_dates(self, tenant_id, shop_id):
        self.calls.append(("latest_dates", tenant_id, shop_id))
        return {
            "creators": date(2026, 8, 28),
            "videos": date(2026, 8, 26),
        }


class FakeIntentRepository:
    def __init__(self) -> None:
        self.calls = []

    async def enqueue(self, tenant_id, queries, *, reuse_succeeded=False):
        self.calls.append((tenant_id, queries, reuse_succeeded))
        return [
            AffiliateCaptureIntentReceipt(
                run_id=uuid4(),
                resource=query.resource.value,
                resource_type=f"affiliate_{query.resource.value[:-1]}",
                status="queued",
                existing=False,
            )
            for query in queries
        ]


class FakeHealthRedis:
    def __init__(self) -> None:
        self.requested_keys = []

    async def get(self, _key):
        self.requested_keys.append(_key)
        return json.dumps(
            {
                "state": "captcha",
                "cdpAvailable": True,
                "sessionAvailable": False,
                "updatedAt": "2026-08-28T01:00:00+00:00",
                "recoveredAt": None,
                "latestAvailableDate": "2026-08-29",
                "latestAvailableDates": {
                    "creators": "2026-08-29",
                    "videos": "2026-08-27",
                },
            }
        )


class FakeExpiredHealthRedis:
    async def get(self, _key):
        return None


class FakeSourceResolver:
    async def source_kind(self, tenant_id, shop_id):
        return "official_api"


class FakeSyncRepository:
    def __init__(self):
        self.calls = []

    async def create_run(self, tenant_id, shop_id, **kwargs):
        run_id = uuid4()
        self.calls.append((tenant_id, shop_id, kwargs, run_id))
        return run_id

    async def cancel_run(self, tenant_id, run_id):
        raise AssertionError("Official test job should enqueue successfully.")


class FakeOfficialQueue:
    def __init__(self):
        self.calls = []

    async def enqueue_job(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return object()

    async def get(self, _key):
        return None


def _client(permissions: list[str]):
    tenant_id, user_id = uuid4(), uuid4()
    app = FastAPI()
    app.include_router(affiliate_center_stable.router, prefix="/api")
    repository = FakeReadRepository()
    intent_repository = FakeIntentRepository()
    app.state.affiliate_center_read_repository = repository
    app.state.affiliate_capture_intent_repository = intent_repository
    health_redis = FakeHealthRedis()
    app.state.arq_queue = health_redis
    app.dependency_overrides[require_session] = lambda: AuthSession(user_id, tenant_id)
    app.dependency_overrides[get_authenticated_user] = lambda: CurrentUser(
        user_id, "Admin", "admin", [], permissions
    )
    return TestClient(app), repository, intent_repository, health_redis


def _params(shop_id):
    return {
        "shopId": str(shop_id),
        "from": "2026-08-01",
        "to": "2026-08-07",
        "currency": "usd",
        "page": 2,
        "pageSize": 25,
    }


def test_creator_query_builds_the_frozen_shop_local_window() -> None:
    client, repository, _, _ = _client([AFFILIATE_CENTER_VIEW])
    shop_id = uuid4()

    response = client.get(
        "/api/affiliate-center/creators",
        params={**_params(shop_id), "sort": "affiliateGmvMinor", "order": "desc"},
    )

    assert response.status_code == 200
    call = repository.calls[-1]
    assert call[0] == "creators"
    assert call[2].window_start == date(2026, 8, 1)
    assert call[2].window_end == date(2026, 8, 7)
    assert call[2].shop_timezone == "America/Los_Angeles"
    assert call[2].currency == "USD"
    assert call[3:] == (2, 25, "affiliateGmvMinor", "desc")


def test_video_query_forwards_creator_filter_and_server_sort() -> None:
    client, repository, _, _ = _client([AFFILIATE_CENTER_VIEW])

    response = client.get(
        "/api/affiliate-center/videos",
        params={
            **_params(uuid4()),
            "sort": "views",
            "order": "asc",
            "creatorOpenId": "creator-open-1",
        },
    )

    assert response.status_code == 200
    assert repository.calls[-1][3:] == (2, 25, "views", "asc", "creator-open-1")


def test_sync_status_is_shop_scoped_and_permission_protected() -> None:
    shop_id = uuid4()
    denied = _client([])[0].get(
        "/api/affiliate-center/sync-status", params={"shopId": str(shop_id)}
    )
    client, repository, _, health_redis = _client([AFFILIATE_CENTER_VIEW])
    response = client.get(
        "/api/affiliate-center/sync-status", params={"shopId": str(shop_id)}
    )

    assert denied.status_code == 403
    assert response.status_code == 200
    assert response.json()["items"][0]["status"] == "never_synced"
    assert response.json()["browser"]["state"] == "captcha"
    assert response.json()["browser"]["cdpAvailable"] is True
    assert response.json()["browser"]["latestAvailableDate"] == "2026-08-29"
    assert response.json()["browser"]["latestAvailableDates"] == {
        "creators": "2026-08-29",
        "videos": "2026-08-27",
    }
    assert response.json()["latestAvailableDates"] == {
        "creators": "2026-08-28",
        "videos": "2026-08-26",
    }
    assert repository.calls[-1][0] == "status"
    assert health_redis.requested_keys == [
        f"affiliate:capture-health:{client.app.dependency_overrides[require_session]().tenant_id}:{shop_id}"
    ]


def test_sync_status_restores_dates_from_complete_snapshots_after_health_expires() -> None:
    client, _, _, _ = _client([AFFILIATE_CENTER_VIEW])
    client.app.state.arq_queue = FakeExpiredHealthRedis()

    response = client.get(
        "/api/affiliate-center/sync-status", params={"shopId": str(uuid4())}
    )

    assert response.status_code == 200
    assert response.json()["browser"]["state"] == "browser_offline"
    assert response.json()["latestAvailableDates"] == {
        "creators": "2026-08-28",
        "videos": "2026-08-26",
    }


def test_sync_uses_complete_snapshot_date_after_browser_health_expires() -> None:
    client, _, intents, _ = _client([AFFILIATE_CENTER_VIEW, SYNC_TRIGGER])
    client.app.state.arq_queue = FakeExpiredHealthRedis()

    accepted = client.post(
        "/api/affiliate-center/sync",
        json={
            "shopId": str(uuid4()),
            "from": "2026-08-28",
            "to": "2026-08-28",
            "currency": "USD",
            "resources": ["creators"],
        },
    )
    rejected = client.post(
        "/api/affiliate-center/sync",
        json={
            "shopId": str(uuid4()),
            "from": "2026-08-29",
            "to": "2026-08-29",
            "currency": "USD",
            "resources": ["creators"],
        },
    )

    assert accepted.status_code == 202
    assert len(intents.calls) == 1
    assert rejected.status_code == 422
    assert "2026-08-28" in rejected.json()["detail"]


def test_sync_creates_daily_browser_daemon_owned_queued_intents() -> None:
    client, _, intents, _ = _client([AFFILIATE_CENTER_VIEW, SYNC_TRIGGER])

    response = client.post(
        "/api/affiliate-center/sync",
        json={
            "shopId": str(uuid4()),
            "from": "2026-08-01",
            "to": "2026-08-07",
            "currency": "USD",
            "resources": ["creators", "videos"],
        },
    )

    assert response.status_code == 202
    assert response.json()["captureMode"] == "browser_daemon_owned"
    resources = [item["resource"] for item in response.json()["items"]]
    assert resources == ["creators"] * 7 + ["videos"] * 7
    assert all(item["status"] == "queued" for item in response.json()["items"])
    assert len(intents.calls) == 2
    assert all(call[2] is True for call in intents.calls)
    assert all(
        query.window_start == query.window_end
        for call in intents.calls
        for query in call[1]
    )


def test_official_shop_sync_bypasses_browser_health_and_capture_intents() -> None:
    client, _, intents, _ = _client([AFFILIATE_CENTER_VIEW, SYNC_TRIGGER])
    sync_repository = FakeSyncRepository()
    queue = FakeOfficialQueue()
    client.app.state.affiliate_source_resolver = FakeSourceResolver()
    client.app.state.analytics_sync_repository = sync_repository
    client.app.state.arq_queue = queue

    response = client.post(
        "/api/affiliate-center/sync",
        json={
            "shopId": str(uuid4()),
            "from": "2026-08-30",
            "to": "2026-08-30",
            "currency": "USD",
            "resources": ["creators", "videos"],
        },
    )

    assert response.status_code == 202
    assert response.json()["captureMode"] == "official_api_owned"
    assert [item["resource"] for item in response.json()["items"]] == [
        "creators",
        "videos",
    ]
    assert intents.calls == []
    assert len(sync_repository.calls) == 2
    assert len(queue.calls) == 2
    assert all(call[0][0] == "sync_official_affiliate_job" for call in queue.calls)


def test_official_custom_window_is_scoped_to_the_requested_shop() -> None:
    client, _, intents, _ = _client([AFFILIATE_CENTER_VIEW, SYNC_TRIGGER])
    sync_repository = FakeSyncRepository()
    queue = FakeOfficialQueue()
    client.app.state.affiliate_source_resolver = FakeSourceResolver()
    client.app.state.analytics_sync_repository = sync_repository
    client.app.state.arq_queue = queue
    shop_id = uuid4()

    response = client.post(
        "/api/affiliate-center/sync",
        json={
            "shopId": str(shop_id),
            "from": "2026-08-10",
            "to": "2026-08-12",
            "currency": "USD",
            "resources": ["creators", "videos"],
        },
    )

    assert response.status_code == 202
    assert response.json()["captureMode"] == "official_api_owned"
    assert intents.calls == []
    assert len(queue.calls) == 4
    assert all(call[0][2] == str(shop_id) for call in queue.calls)
    assert [call[0][3] for call in queue.calls] == [
        "creators",
        "creators",
        "creators",
        "videos",
    ]
    assert [call[0][4:6] for call in queue.calls] == [
        ("2026-08-10", "2026-08-10"),
        ("2026-08-11", "2026-08-11"),
        ("2026-08-12", "2026-08-12"),
        ("2026-08-10", "2026-08-12"),
    ]


def test_official_two_month_sync_uses_two_bounded_jobs_per_resource() -> None:
    client, _, intents, _ = _client([AFFILIATE_CENTER_VIEW, SYNC_TRIGGER])
    sync_repository = FakeSyncRepository()
    queue = FakeOfficialQueue()
    client.app.state.affiliate_source_resolver = FakeSourceResolver()
    client.app.state.analytics_sync_repository = sync_repository
    client.app.state.arq_queue = queue

    response = client.post(
        "/api/affiliate-center/sync",
        json={
            "shopId": str(uuid4()),
            "from": "2026-07-01",
            "to": "2026-08-29",
            "currency": "USD",
            "resources": ["creators", "videos"],
        },
    )

    assert response.status_code == 202
    assert response.json()["captureMode"] == "official_api_owned"
    assert len(queue.calls) == 4
    windows = [(call[0][4], call[0][5]) for call in queue.calls]
    assert windows == [
        ("2026-07-01", "2026-07-30"),
        ("2026-07-31", "2026-08-29"),
        ("2026-07-01", "2026-07-30"),
        ("2026-07-31", "2026-08-29"),
    ]
    assert intents.calls == []


def test_sync_splits_the_two_month_video_window_into_daily_intents() -> None:
    client, _, intents, _ = _client([AFFILIATE_CENTER_VIEW, SYNC_TRIGGER])

    response = client.post(
        "/api/affiliate-center/sync",
        json={
            "shopId": str(uuid4()),
            "from": "2026-06-26",
            "to": "2026-08-25",
            "currency": "USD",
            "resources": ["videos"],
        },
    )

    assert response.status_code == 202
    queries = intents.calls[0][1]
    assert len(queries) == 61
    assert (queries[0].window_start, queries[0].window_end) == (
        date(2026, 6, 26),
        date(2026, 6, 26),
    )
    assert (queries[-1].window_start, queries[-1].window_end) == (
        date(2026, 8, 25),
        date(2026, 8, 25),
    )
    assert intents.calls[0][2] is True


def test_sync_uses_the_latest_date_observed_in_tiktok() -> None:
    client, _, intents, _ = _client([AFFILIATE_CENTER_VIEW, SYNC_TRIGGER])

    accepted = client.post(
        "/api/affiliate-center/sync",
        json={
            "shopId": str(uuid4()),
            "from": "2026-08-29",
            "to": "2026-08-29",
            "currency": "USD",
            "resources": ["creators"],
        },
    )
    rejected = client.post(
        "/api/affiliate-center/sync",
        json={
            "shopId": str(uuid4()),
            "from": "2026-08-30",
            "to": "2026-08-30",
            "currency": "USD",
            "resources": ["creators"],
        },
    )

    assert accepted.status_code == 202
    assert len(intents.calls) == 1
    assert rejected.status_code == 422
    assert "2026-08-29" in rejected.json()["detail"]


def test_sync_validates_each_resource_against_its_own_tiktok_date() -> None:
    client, _, intents, _ = _client([AFFILIATE_CENTER_VIEW, SYNC_TRIGGER])

    response = client.post(
        "/api/affiliate-center/sync",
        json={
            "shopId": str(uuid4()),
            "from": "2026-08-28",
            "to": "2026-08-29",
            "currency": "USD",
            "resources": ["videos"],
        },
    )

    assert response.status_code == 422
    assert "2026-08-27" in response.json()["detail"]
    assert intents.calls == []
