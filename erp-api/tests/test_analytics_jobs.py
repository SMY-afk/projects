import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from erp_api.workers.analytics_jobs import (
    enqueue_hourly_video_syncs,
    enqueue_scheduled_analytics_syncs,
    purge_analytics_raw_payloads_job,
    sync_analytics_job,
)


class FakeScalars:
    def __init__(self, values) -> None:
        self._values = values

    def all(self):
        return self._values


class FakeSystemSession:
    async def scalars(self, statement):
        return FakeScalars([uuid4()])

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None


class FakeShopSession:
    def __init__(self, shop_id) -> None:
        self.shop_id = shop_id

    async def execute(self, statement):
        return FakeScalars([(self.shop_id, "America/Los_Angeles")])


class FakeDatabase:
    def __init__(self) -> None:
        self.shop_id = uuid4()
        self.system_session_factory = lambda: FakeSystemSession()

    async def session(self, tenant_id):
        yield FakeShopSession(self.shop_id)


class FakeRedis:
    def __init__(self) -> None:
        self.jobs = []

    async def enqueue_job(self, *args, **kwargs):
        self.jobs.append((args, kwargs))


def test_daily_jobs_queue_video_windows_live_and_rolling_affiliate_live() -> None:
    redis = FakeRedis()
    clock = lambda: datetime(2026, 8, 19, 18, tzinfo=UTC)

    queued = asyncio.run(
        enqueue_scheduled_analytics_syncs(
            {"database": FakeDatabase(), "redis": redis, "clock": clock}
        )
    )

    assert queued == 4
    assert [job[0][3] for job in redis.jobs].count("video") == 2
    live_jobs = [job for job in redis.jobs if job[0][3] == "live"]
    assert len(live_jobs) == 2
    incremental_live = next(job for job in live_jobs if len(job[0]) == 4)
    assert incremental_live[1]["_job_id"].endswith(":live:20260819")
    affiliate_live = next(job for job in live_jobs if len(job[0]) > 4)
    assert affiliate_live[0][4:8] == (
        "2026-08-13T07:00:00+00:00",
        "2026-08-20T07:00:00+00:00",
        "USD",
        "AFFILIATE_ACCOUNTS",
    )
    assert ":live-affiliate:" in affiliate_live[1]["_job_id"]
    windows = {(job[0][4], job[0][5]) for job in redis.jobs if job[0][3] == "video"}
    assert windows == {
        ("2026-08-13T07:00:00+00:00", "2026-08-20T07:00:00+00:00"),
        ("2026-07-21T07:00:00+00:00", "2026-08-20T07:00:00+00:00"),
    }
    job_ids = {job[1]["_job_id"] for job in redis.jobs}
    assert len(job_ids) == 4
    assert all(job_id.startswith("analytics-sync:") for job_id in job_ids)
    assert all(job[1]["source_kind"] == "official_api" for job in redis.jobs)


def test_hourly_job_queues_only_the_shop_today_window() -> None:
    redis = FakeRedis()

    queued = asyncio.run(
        enqueue_hourly_video_syncs(
            {
                "database": FakeDatabase(),
                "redis": redis,
                "clock": lambda: datetime(2026, 8, 19, 18, 45, tzinfo=UTC),
            }
        )
    )

    assert queued == 1
    args, kwargs = redis.jobs[0]
    assert args[3] == "video"
    assert args[4:6] == (
        "2026-08-19T07:00:00+00:00",
        "2026-08-20T07:00:00+00:00",
    )
    assert kwargs["_job_id"].endswith(":2026081918")


class CapturingSyncService:
    def __init__(self) -> None:
        self.kwargs = None

    async def sync(self, tenant_id, **kwargs):
        self.kwargs = kwargs


@pytest.mark.parametrize("resource_type", ["affiliate_creator", "affiliate_video"])
def test_arq_job_rejects_browser_affiliate_resources(resource_type: str) -> None:
    service = CapturingSyncService()

    with pytest.raises(ValueError, match="daemon-owned"):
        asyncio.run(
            sync_analytics_job(
                {
                    "analytics_sync_service": service,
                    "analytics_sync_max_tries": 5,
                },
                str(uuid4()),
                str(uuid4()),
                resource_type,
                source_kind="page_capture",
            )
        )

    assert service.kwargs is None


@pytest.mark.parametrize("resource_type", ["affiliate_creator", "affiliate_video"])
def test_arq_rejects_affiliate_resource_without_official_source(
    resource_type: str,
) -> None:
    service = CapturingSyncService()

    with pytest.raises(ValueError, match="No ARQ official API source"):
        asyncio.run(
            sync_analytics_job(
                {
                    "analytics_sync_service": service,
                    "analytics_sync_max_tries": 5,
                },
                str(uuid4()),
                str(uuid4()),
                resource_type,
            )
        )

    assert service.kwargs is None


def test_worker_forwards_the_explicit_video_window() -> None:
    service = CapturingSyncService()

    asyncio.run(
        sync_analytics_job(
            {
                "analytics_sync_service": service,
                "analytics_sync_max_tries": 5,
                "job_id": "analytics-video-window:test",
            },
            str(uuid4()),
            str(uuid4()),
            "video",
            "2026-08-01T00:00:00+00:00",
            "2026-08-16T00:00:00+00:00",
            "USD",
            "ALL",
        )
    )

    assert service.kwargs["window_start"] == datetime(2026, 8, 1, tzinfo=UTC)
    assert service.kwargs["window_end"] == datetime(2026, 8, 16, tzinfo=UTC)


class CapturingRawPayloadRepository:
    def __init__(self, removed: int) -> None:
        self.removed = removed
        self.tenant_ids = []

    async def purge_expired_raw_payloads(self, tenant_id):
        self.tenant_ids.append(tenant_id)
        return self.removed

    async def clear_expired_raw_payloads(self, tenant_id):
        self.tenant_ids.append(tenant_id)
        return self.removed


def test_raw_payload_cron_clears_bestseller_raw_without_deleting_entries() -> None:
    analytics_repository = CapturingRawPayloadRepository(2)
    bestseller_repository = CapturingRawPayloadRepository(3)

    removed = asyncio.run(
        purge_analytics_raw_payloads_job(
            {
                "database": FakeDatabase(),
                "analytics_sync_repository": analytics_repository,
                "bestseller_repository": bestseller_repository,
            }
        )
    )

    assert removed == 5
    assert len(analytics_repository.tenant_ids) == 1
    assert bestseller_repository.tenant_ids == analytics_repository.tenant_ids
