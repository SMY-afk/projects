from types import SimpleNamespace
from uuid import uuid4

import pytest

from erp_api.workers.logistics_tracking_jobs import (
    enqueue_due_logistics_tracking_polls,
    poll_logistics_tracking_job,
    sync_tiktok_logistics_job,
)
from erp_api.workers.settings import WorkerSettings


class FakeRedis:
    def __init__(self) -> None:
        self.calls = []

    async def enqueue_job(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return object()


@pytest.mark.asyncio
async def test_sweeper_enqueues_due_tracking_poll_with_stable_job_id() -> None:
    tenant_id, waybill_id = uuid4(), uuid4()

    async def list_due_polls():
        return [(tenant_id, waybill_id, 2)]

    redis = FakeRedis()
    count = await enqueue_due_logistics_tracking_polls(
        {
            "logistics_tracking_repository": SimpleNamespace(
                list_due_polls=list_due_polls
            ),
            "redis": redis,
        }
    )

    assert count == 1
    assert redis.calls[0][1]["_job_id"] == f"logistics-tracking:{waybill_id}:2"


def test_tracking_jobs_are_registered() -> None:
    assert poll_logistics_tracking_job in WorkerSettings.functions
    assert enqueue_due_logistics_tracking_polls in WorkerSettings.functions
    assert sync_tiktok_logistics_job in WorkerSettings.functions
    assert any(
        job.coroutine is enqueue_due_logistics_tracking_polls
        for job in WorkerSettings.cron_jobs
    )
    assert any(
        job.coroutine is sync_tiktok_logistics_job for job in WorkerSettings.cron_jobs
    )


def test_tiktok_logistics_cron_has_a_dedicated_timeout() -> None:
    job = next(
        job
        for job in WorkerSettings.cron_jobs
        if job.coroutine is sync_tiktok_logistics_job
    )

    assert job.timeout_s == 900
    assert job.job_id == "cron:sync-tiktok-logistics"
