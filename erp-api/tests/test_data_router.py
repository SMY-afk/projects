import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from erp_api.routers.data import AdminResyncRequest, list_trends, overview, resync_data
from erp_api.services.analytics_repository import StoredAnalyticsSnapshot


class FakeRepository:
    def __init__(self) -> None:
        self.calls = []

    async def list_snapshots(self, tenant_id, shop_id, **kwargs):
        self.calls.append((tenant_id, shop_id, kwargs))
        return [
            StoredAnalyticsSnapshot(
                metric_set="shop",
                granularity="day",
                window_start=datetime(2026, 8, 1, tzinfo=UTC),
                window_end=datetime(2026, 8, 2, tzinfo=UTC),
                currency="USD",
                metrics={"views": 12},
                source_updated_at=None,
                captured_at=datetime(2026, 8, 2, tzinfo=UTC),
            )
        ]

    async def shop_exists(self, tenant_id, shop_id):
        return True

    async def get_shop_timezone(self, tenant_id, shop_id):
        return "UTC"


class EmptyRepository(FakeRepository):
    async def list_snapshots(self, tenant_id, shop_id, **kwargs):
        self.calls.append((tenant_id, shop_id, kwargs))
        return []


class MissingShopRepository(FakeRepository):
    async def shop_exists(self, tenant_id, shop_id):
        return False


class FakeRedis:
    def __init__(self) -> None:
        self.calls = []

    async def enqueue_job(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return object() if len(self.calls) == 1 else None


def test_snapshot_route_reads_only_local_repository() -> None:
    repository = FakeRepository()
    tenant_id, shop_id = uuid4(), uuid4()

    response = asyncio.run(
        list_trends(
            shop_id=shop_id,
            metric_set="shop",
            granularity="day",
            from_=datetime(2026, 8, 1, tzinfo=UTC),
            to=datetime(2026, 8, 3, tzinfo=UTC),
            currency="USD",
            session=SimpleNamespace(tenant_id=tenant_id),
            _=SimpleNamespace(),
            repository=repository,
            read_repository=repository,
        )
    )

    assert response.source == "local_snapshot"
    assert response.data[0].metrics == {"views": 12}
    assert repository.calls[0][2]["window_start"] == datetime(2026, 8, 1, tzinfo=UTC)


def test_snapshot_route_marks_missing_local_data_stale() -> None:
    repository = EmptyRepository()
    tenant_id, shop_id = uuid4(), uuid4()

    response = asyncio.run(
        list_trends(
            shop_id=shop_id,
            metric_set="shop",
            granularity="day",
            from_=datetime(2026, 8, 1, tzinfo=UTC),
            to=datetime(2026, 8, 3, tzinfo=UTC),
            currency="USD",
            session=SimpleNamespace(tenant_id=tenant_id),
            _=SimpleNamespace(),
            repository=repository,
            read_repository=repository,
        )
    )

    assert response.data == []
    assert response.freshness.isStale is True
    assert response.errors[0].code == "data_unavailable"
    assert response.errors[0].action == "resync"


def test_overview_aggregates_daily_video_and_live_metrics_without_mixing_metric_meanings() -> (
    None
):
    repository = FakeRepository()
    repository.list_snapshots = lambda *args, **kwargs: None

    async def list_snapshots(*args, **kwargs):
        return [
            StoredAnalyticsSnapshot(
                metric_set="trend",
                granularity="day",
                window_start=datetime(2026, 8, 1, tzinfo=UTC),
                window_end=datetime(2026, 8, 2, tzinfo=UTC),
                currency="USD",
                metrics={
                    "videoGmv": {"amountMinor": 1234, "currency": "USD"},
                    "videoOrders": 3,
                    "videoProductClicks": 25,
                    "liveGmv": {"amountMinor": 456, "currency": "USD"},
                    "liveOrders": 1,
                    "liveCustomers": 1,
                    "liveClickToOrderRate": 0.25,
                },
                source_updated_at=None,
                captured_at=datetime(2026, 8, 2, tzinfo=UTC),
            )
        ]

    repository.list_snapshots = list_snapshots
    response = asyncio.run(
        overview(
            shop_id=uuid4(),
            from_=datetime(2026, 8, 1, tzinfo=UTC),
            to=datetime(2026, 8, 3, tzinfo=UTC),
            currency="USD",
            session=SimpleNamespace(tenant_id=uuid4()),
            _=SimpleNamespace(),
            repository=repository,
            read_repository=repository,
        )
    )

    assert response.data[0].metrics == {
        "gmv": {"amountMinor": 1690, "currency": "USD"},
        "orders": 4,
        "videoProductClicks": 25,
        "liveCustomers": 1,
        "latestLiveClickToOrderRate": 0.25,
    }


def test_snapshot_route_hides_other_tenant_shop_as_not_found() -> None:
    repository = MissingShopRepository()

    with pytest.raises(HTTPException, match="Shop was not found") as raised:
        asyncio.run(
            list_trends(
                shop_id=uuid4(),
                metric_set="shop",
                granularity="day",
                from_=datetime(2026, 8, 1, tzinfo=UTC),
                to=datetime(2026, 8, 3, tzinfo=UTC),
                currency="USD",
                session=SimpleNamespace(tenant_id=uuid4()),
                _=SimpleNamespace(),
                repository=repository,
                read_repository=repository,
            )
        )

    assert raised.value.status_code == 404


def test_admin_resync_only_enqueues_deduplicated_jobs() -> None:
    redis = FakeRedis()
    shop_id, tenant_id = uuid4(), uuid4()
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(analytics_sync_service=object(), arq_queue=redis)
        )
    )

    response = asyncio.run(
        resync_data(
            AdminResyncRequest(shopId=shop_id),
            request,
            session=SimpleNamespace(tenant_id=tenant_id),
            _data=SimpleNamespace(),
            _=SimpleNamespace(),
            repository=FakeRepository(),
        )
    )

    assert response.source == "queue"
    assert len(response.data.jobIds) == 1
    assert len(response.data.alreadyQueued) == 1
    assert {call[1]["_job_id"] for call in redis.calls} == {
        f"analytics-sync:{shop_id}:video",
        f"analytics-sync:{shop_id}:live",
    }
    assert all(call[1]["source_kind"] == "official_api" for call in redis.calls)


def test_admin_resync_schema_does_not_claim_browser_capture_support() -> None:
    with pytest.raises(ValidationError):
        AdminResyncRequest(
            shopId=uuid4(),
            resourceTypes=["affiliate_creator"],
        )


def test_admin_resync_queues_an_exact_video_window_without_fallback() -> None:
    redis = FakeRedis()
    shop_id, tenant_id = uuid4(), uuid4()
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                analytics_sync_service=object(),
                arq_queue=redis,
                clock=lambda: datetime(2026, 8, 19, 12, 34, tzinfo=UTC),
            )
        )
    )

    response = asyncio.run(
        resync_data(
            AdminResyncRequest(
                shopId=shop_id,
                resourceTypes=["video"],
                windowStart="2026-08-01T00:00:00Z",
                windowEnd="2026-08-16T00:00:00Z",
                currency="USD",
                accountType="ALL",
            ),
            request,
            session=SimpleNamespace(tenant_id=tenant_id),
            _data=SimpleNamespace(),
            _=SimpleNamespace(),
            repository=FakeRepository(),
        )
    )

    assert len(response.data.jobIds) == 1
    args, kwargs = redis.calls[0]
    assert args[3:] == (
        "video",
        "2026-08-01T00:00:00+00:00",
        "2026-08-16T00:00:00+00:00",
        "USD",
        "ALL",
    )
    assert kwargs["_job_id"].endswith(":202608191234")
