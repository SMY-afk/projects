from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from erp_api.workers.finance_jobs import (
    enqueue_scheduled_finance_syncs,
    sync_finance_job,
)
from erp_api.workers.settings import WorkerSettings


class CapturingService:
    def __init__(self, status="succeeded") -> None:
        self.kwargs = None
        self.status = status

    async def sync(self, tenant_id, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(status=self.status)


def test_finance_job_forwards_explicit_backfill_window_and_attempt() -> None:
    service = CapturingService()

    asyncio.run(
        sync_finance_job(
            {
                "finance_sync_service": service,
                "finance_sync_max_tries": 5,
                "job_try": 2,
            },
            str(uuid4()),
            str(uuid4()),
            "backfill",
            "2026-07-22T00:00:00+00:00",
            "2026-08-21T00:00:00+00:00",
            "manual",
        )
    )

    assert service.kwargs["mode"] == "backfill"
    assert service.kwargs["attempt"] == 2
    assert service.kwargs["window_from"] == datetime(2026, 7, 22, tzinfo=UTC)


def test_retry_wait_raises_for_arq_retry_but_dead_letter_does_not() -> None:
    with pytest.raises(RuntimeError, match="tenant-scoped sync run"):
        asyncio.run(
            sync_finance_job(
                {
                    "finance_sync_service": CapturingService("retry_wait"),
                    "finance_sync_max_tries": 5,
                },
                str(uuid4()),
                str(uuid4()),
            )
        )

    result = asyncio.run(
        sync_finance_job(
            {
                "finance_sync_service": CapturingService("dead_letter"),
                "finance_sync_max_tries": 5,
            },
            str(uuid4()),
            str(uuid4()),
        )
    )
    assert result.status == "dead_letter"


class FakeRedis:
    def __init__(self) -> None:
        self.jobs = []

    async def enqueue_job(self, *args, **kwargs):
        self.jobs.append((args, kwargs))


def test_scheduler_queues_incremental_job_per_authorized_shop(monkeypatch) -> None:
    tenant_id, shop_id = uuid4(), uuid4()
    redis = FakeRedis()

    async def authorized(database):
        return [(tenant_id, shop_id)]

    monkeypatch.setattr("erp_api.workers.finance_jobs._authorized_shops", authorized)
    queued = asyncio.run(
        enqueue_scheduled_finance_syncs(
            {
                "database": object(),
                "redis": redis,
                "clock": lambda: datetime(2026, 8, 21, 4, tzinfo=UTC),
            }
        )
    )

    assert queued == 1
    args, kwargs = redis.jobs[0]
    assert args[:4] == (
        "sync_finance_job",
        str(tenant_id),
        str(shop_id),
        "incremental",
    )
    assert kwargs["_job_id"].endswith(":202608210400")


def test_worker_registers_finance_job_every_fifteen_minutes() -> None:
    assert any(
        getattr(job, "coroutine", job) is sync_finance_job
        for job in WorkerSettings.functions
    )
    assert enqueue_scheduled_finance_syncs in WorkerSettings.functions
    scheduled = next(
        job
        for job in WorkerSettings.cron_jobs
        if job.coroutine is enqueue_scheduled_finance_syncs
    )
    assert scheduled.hour is None
    assert scheduled.minute == {0, 15, 30, 45}
