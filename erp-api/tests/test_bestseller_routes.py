from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from erp_api.core.errors import register_exception_handlers
from erp_api.core.permissions import BESTSELLERS_VIEW, SYNC_TRIGGER
from erp_api.routers import bestsellers
from erp_api.routers.auth import get_authenticated_user, require_session
from erp_api.services.auth import AuthSession, CurrentUser
from erp_api.services.bestseller_read_repository import (
    StoredBestsellerEntry,
    StoredBestsellerSnapshot,
)


class FakeShopRepository:
    def __init__(self, *, scopes=None, status="authorized") -> None:
        self.scopes = scopes or []
        self.status = status

    async def get_connection_status(self, tenant_id, shop_id):
        return {
            "shopId": str(shop_id),
            "platformShopId": "platform-shop",
            "shopName": "Demo Shop",
            "region": "US",
            "timezone": "UTC",
            "status": self.status,
            "expiresAt": None,
            "updatedAt": datetime(2026, 8, 20, 3, tzinfo=UTC),
            "scopes": self.scopes,
        }


class FakeReadRepository:
    def __init__(self, snapshot) -> None:
        self.snapshot = snapshot
        self.calls = []

    async def get_snapshot(self, tenant_id, query):
        self.calls.append((tenant_id, query))
        return self.snapshot


class FakeQueue:
    def __init__(self) -> None:
        self.calls = []

    async def enqueue_job(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return object() if len(self.calls) % 2 else None


def _snapshot(*, stale: bool = False) -> StoredBestsellerSnapshot:
    return StoredBestsellerSnapshot(
        platform_request_id="platform-request-1",
        entry_count=1,
        is_stale=stale,
        last_error_category="rate_limited" if stale else None,
        last_error_at=datetime(2026, 8, 20, 5, tzinfo=UTC) if stale else None,
        refreshed_at=datetime(2026, 8, 20, 4, tzinfo=UTC),
        entries=(
            StoredBestsellerEntry(
                external_id="product-1",
                rank=1,
                display_name="Product 1",
                gmv_range_raw="$1K-$2K",
                gmv_currency_context="USD",
                extensions={"rating": "4.8"},
            ),
        ),
    )


def _client(*, permissions, snapshot=None, scopes=None):
    tenant_id, user_id = uuid4(), uuid4()
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(bestsellers.router, prefix="/api")
    app.state.shop_repository = FakeShopRepository(
        scopes=scopes or ["data.bestselling.public.read"]
    )
    app.state.bestseller_read_repository = FakeReadRepository(snapshot)
    app.state.bestseller_sync_service = object()
    app.state.arq_queue = FakeQueue()
    app.dependency_overrides[require_session] = lambda: AuthSession(user_id, tenant_id)
    app.dependency_overrides[get_authenticated_user] = lambda: CurrentUser(
        user_id, "Admin", "admin", [], permissions
    )
    return TestClient(app), app


def test_authorization_status_reports_missing_scope_without_exposing_tokens() -> None:
    client, _ = _client(permissions=[BESTSELLERS_VIEW], scopes=["shops.read"])

    response = client.get(
        "/api/bestsellers/authorization-status", params={"shopId": str(uuid4())}
    )

    assert response.status_code == 200
    assert response.json() == {
        "apiVersion": "v1",
        "source": "local_connection",
        "data": {
            "shopId": response.json()["data"]["shopId"],
            "status": "reauthorization_required",
            "requiredScopes": ["data.bestselling.public.read"],
            "grantedScopes": ["shops.read"],
            "missingScopes": ["data.bestselling.public.read"],
            "canRead": False,
        },
        "freshness": {
            "isStale": False,
            "asOf": "2026-08-20T03:00:00Z",
            "lastErrorAt": None,
        },
        "errors": [
            {
                "code": "reauthorization_required",
                "message": "TikTok Shop authorization must be renewed.",
                "action": "reauthorize",
            }
        ],
    }
    assert "token" not in response.text.lower()


def test_four_read_routes_return_only_normalized_local_snapshot_fields() -> None:
    client, app = _client(permissions=[BESTSELLERS_VIEW], snapshot=_snapshot())

    for entity_type in ("products", "creators", "videos", "lives"):
        params = {
            "shopId": str(uuid4()),
            "date": "2026-08-19",
            "timeSlot": "7D",
            "currency": "USD",
        }
        if entity_type == "creators":
            params["authorType"] = "ALL"
        response = client.get(f"/api/bestsellers/{entity_type}", params=params)
        assert response.status_code == 200
        body = response.json()
        assert body["source"] == "local_snapshot"
        assert set(body) == {"apiVersion", "source", "data", "freshness", "errors"}
        assert body["data"]["query"]["date"] == "2026-08-19"
        assert body["data"]["items"][0]["gmv"] == {
            "raw": "$1K-$2K",
            "currencyContext": "USD",
            "computable": False,
        }
        assert "rawPayload" not in body["data"]["items"][0]

    calls = app.state.bestseller_read_repository.calls
    assert [call[1].entity_type for call in calls] == [
        "product",
        "creator",
        "video",
        "live",
    ]


def test_stale_snapshot_keeps_entries_and_exposes_safe_failure_category() -> None:
    client, _ = _client(permissions=[BESTSELLERS_VIEW], snapshot=_snapshot(stale=True))

    response = client.get(
        "/api/bestsellers/products",
        params={
            "shopId": str(uuid4()),
            "date": "2026-08-19",
            "timeSlot": "1D",
            "currency": "USD",
        },
    )

    assert response.status_code == 200
    assert len(response.json()["data"]["items"]) == 1
    assert response.json()["freshness"]["isStale"] is True
    assert response.json()["errors"][0]["code"] == "rate_limited"


def test_missing_snapshot_is_distinct_from_a_successful_empty_top_list() -> None:
    client, _ = _client(permissions=[BESTSELLERS_VIEW], snapshot=None)

    response = client.get(
        "/api/bestsellers/lives",
        params={
            "shopId": str(uuid4()),
            "date": "2026-08-19",
            "timeSlot": "7D",
            "currency": "USD",
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["items"] == []
    assert response.json()["freshness"] == {
        "isStale": True,
        "asOf": None,
        "lastErrorAt": None,
    }
    assert response.json()["errors"][0]["code"] == "data_unavailable"

    empty_snapshot = replace(_snapshot(), entry_count=0, entries=())
    client, _ = _client(permissions=[BESTSELLERS_VIEW], snapshot=empty_snapshot)
    successful_empty = client.get(
        "/api/bestsellers/lives",
        params={
            "shopId": str(uuid4()),
            "date": "2026-08-19",
            "timeSlot": "7D",
            "currency": "USD",
        },
    )
    assert successful_empty.json()["data"]["items"] == []
    assert successful_empty.json()["freshness"]["isStale"] is False
    assert successful_empty.json()["errors"] == []


def test_sync_requires_both_view_and_existing_sync_trigger_permission() -> None:
    client, _ = _client(permissions=[BESTSELLERS_VIEW], snapshot=None)
    payload = {
        "shopId": str(uuid4()),
        "entityTypes": ["products", "creators"],
        "date": "2026-08-19",
        "timeSlot": "30D",
        "currency": "LOCAL",
        "authorType": "AFFILIATE",
    }
    assert client.post("/api/bestsellers/sync", json=payload).status_code == 403

    client, app = _client(permissions=[BESTSELLERS_VIEW, SYNC_TRIGGER], snapshot=None)
    response = client.post("/api/bestsellers/sync", json=payload)

    assert response.status_code == 202
    assert response.json()["source"] == "queue"
    assert len(response.json()["data"]["jobIds"]) == 1
    assert len(response.json()["data"]["alreadyQueued"]) == 1
    assert response.json()["freshness"]["isStale"] is False
    assert response.json()["errors"] == []
    queue_calls = app.state.arq_queue.calls
    assert queue_calls[0][0][3] == "product"
    assert queue_calls[0][0][7] is None
    assert queue_calls[1][0][3] == "creator"
    assert queue_calls[1][0][7] == "AFFILIATE"


def test_sync_rejects_missing_bestseller_scope_without_queueing() -> None:
    client, app = _client(
        permissions=[BESTSELLERS_VIEW, SYNC_TRIGGER],
        snapshot=None,
        scopes=["shops.read"],
    )

    response = client.post(
        "/api/bestsellers/sync",
        json={
            "shopId": str(uuid4()),
            "entityTypes": ["videos"],
            "date": "2026-08-19",
            "timeSlot": "7D",
        },
    )

    assert response.status_code == 409
    assert app.state.arq_queue.calls == []


def test_read_and_authorization_routes_require_bestsellers_view() -> None:
    client, _ = _client(permissions=[], snapshot=_snapshot())

    authorization = client.get(
        "/api/bestsellers/authorization-status", params={"shopId": str(uuid4())}
    )
    listing = client.get(
        "/api/bestsellers/products",
        params={
            "shopId": str(uuid4()),
            "date": date(2026, 8, 19).isoformat(),
            "timeSlot": "7D",
            "currency": "USD",
        },
    )

    assert authorization.status_code == 403
    assert listing.status_code == 403
