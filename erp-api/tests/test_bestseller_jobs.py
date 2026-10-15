from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from arq import Retry

from erp_api.services.bestseller_sync_service import BestsellerSyncError
from erp_api.workers.bestseller_jobs import (
    bestseller_job_id,
    enqueue_scheduled_bestseller_syncs,
    sync_bestseller_job,
)
from erp_api.workers.settings import WorkerSettings


class FakeRows:
    def __init__(self, rows) -> None:
        self._rows = rows

    def all(self):
        return self._rows


class FakeSystemSession:
    def __init__(self, tenant_id) -> None:
        self.tenant_id = tenant_id

    async def scalars(self, statement):
        return FakeRows([self.tenant_id])

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None


class FakeTenantSession:
    def __init__(self, shop_id) -> None:
        self.shop_id = shop_id

    async def execute(self, statement):
        return FakeRows([(self.shop_id, "America/Los_Angeles")])


class FakeDatabase:
    def __init__(self) -> None:
        self.tenant_id = uuid4()
        self.shop_id = uuid4()
        self.system_session_factory = lambda: FakeSystemSession(self.tenant_id)

    async def session(self, tenant_id):
        assert tenant_id == self.tenant_id
        yield FakeTenantSession(self.shop_id)


class FakeRedis:
    def __init__(self) -> None:
        self.jobs = []

    async def enqueue_job(self, *args, **kwargs):
        self.jobs.append((args, kwargs))


class FakeSyncService:
    def __init__(self) -> None:
        self.calls = []

    async def sync(self, tenant_id, **kwargs):
        self.calls.append((tenant_id, kwargs))
        return {"status": "succeeded"}


def test_daily_schedule_enqueues_only_latest_completed_date_for_three_slots() -> None:
    database = FakeDatabase()
    redis = FakeRedis()

    queued = asyncio.run(
        enqueue_scheduled_bestseller_syncs(
            {
                "database": database,
                "redis": redis,
                "clock": lambda: datetime(2026, 8, 21, 6, tzinfo=UTC),
            }
        )
    )

    assert queued == 12
    assert len(redis.jobs) == 12
    assert {job[0][4] for job in redis.jobs} == {"2026-08-19"}
    assert {job[0][5] for job in redis.jobs} == {"1D", "7D", "30D"}
    assert {job[0][3] for job in redis.jobs} == {
        "product",
        "creator",
        "video",
        "live",
    }
    assert all(job[0][6] == "USD" for job in redis.jobs)
    assert all(
        job[0][7] == ("ALL" if job[0][3] == "creator" else None) for job in redis.jobs
    )
    assert len({job[1]["_job_id"] for job in redis.jobs}) == 12


def test_manual_job_syncs_one_explicit_historical_date_without_backfill() -> None:
    service = FakeSyncService()
    tenant_id, shop_id = uuid4(), uuid4()

    result = asyncio.run(
        sync_bestseller_job(
            {"bestseller_sync_service": service},
            str(tenant_id),
            str(shop_id),
            "video",
            "2026-01-15",
            "7D",
            "LOCAL",
            None,
        )
    )

    assert result == {"status": "succeeded"}
    assert len(service.calls) == 1
    assert service.calls[0][0] == tenant_id
    assert service.calls[0][1] == {
        "shop_id": shop_id,
        "entity_type": "video",
        "reference_date": date(2026, 1, 15),
        "time_slot": "7D",
        "currency": "LOCAL",
        "author_type": None,
    }


def test_worker_registers_manual_and_daily_bestseller_jobs() -> None:
    assert sync_bestseller_job in WorkerSettings.functions
    assert enqueue_scheduled_bestseller_syncs in WorkerSettings.functions
    scheduled = next(
        job
        for job in WorkerSettings.cron_jobs
        if job.coroutine is enqueue_scheduled_bestseller_syncs
    )
    assert scheduled.hour == 5
    assert scheduled.minute == 0


def test_job_id_deduplicates_by_every_query_dimension() -> None:
    tenant_id, shop_id = uuid4(), uuid4()
    base = {
        "tenant_id": tenant_id,
        "shop_id": shop_id,
        "entity_type": "creator",
        "reference_date": date(2026, 8, 19),
        "time_slot": "7D",
        "currency": "USD",
        "author_type": "ALL",
    }
    dimensions = [
        {"tenant_id": uuid4()},
        {"shop_id": uuid4()},
        {"entity_type": "product", "author_type": None},
        {"reference_date": date(2026, 8, 18)},
        {"time_slot": "30D"},
        {"currency": "LOCAL"},
        {"author_type": "AFFILIATE"},
    ]
    job_ids = {bestseller_job_id(**base)}
    job_ids.update(bestseller_job_id(**(base | change)) for change in dimensions)

    assert len(job_ids) == 1 + len(dimensions)


def test_rate_limit_is_retried_but_reauthorization_is_not() -> None:
    class FailingService:
        def __init__(self, error: BestsellerSyncError) -> None:
            self.error = error

        async def sync(self, tenant_id, **kwargs):
            raise self.error

    args = (
        str(uuid4()),
        str(uuid4()),
        "product",
        "2026-08-19",
        "1D",
    )
    rate_limited = BestsellerSyncError(
        "rate limited",
        category="rate_limited",
        retryable=True,
        retry_after_seconds=5,
        snapshot_marked_stale=True,
    )
    with pytest.raises(Retry) as retry:
        asyncio.run(
            sync_bestseller_job(
                {"bestseller_sync_service": FailingService(rate_limited)},
                *args,
            )
        )
    assert retry.value.defer_score == 5000

    reauthorization = BestsellerSyncError(
        "reauthorization required",
        category="reauthorization_required",
        retryable=False,
        snapshot_marked_stale=True,
    )
    result = asyncio.run(
        sync_bestseller_job(
            {"bestseller_sync_service": FailingService(reauthorization)},
            *args,
        )
    )
    assert result == {
        "status": "failed",
        "errorCategory": "reauthorization_required",
        "retryable": False,
        "snapshotMarkedStale": True,
    }
