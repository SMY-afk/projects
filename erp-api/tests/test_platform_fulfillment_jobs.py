from types import SimpleNamespace
from uuid import uuid4

import pytest
from arq import Retry

from erp_api.workers.platform_fulfillment_jobs import (
    enqueue_due_platform_fulfillments,
    enqueue_platform_fulfillment,
    process_platform_fulfillment_job,
)
from erp_api.workers.settings import WorkerSettings


class FakeRedis:
    def __init__(self) -> None:
        self.calls = []

    async def enqueue_job(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return object()


class ExistingJobRedis(FakeRedis):
    async def enqueue_job(self, *args, **kwargs):
        self.calls.append((args, kwargs))


@pytest.mark.asyncio
async def test_enqueue_uses_deterministic_attempt_job_id() -> None:
    redis = FakeRedis()
    event_id = str(uuid4())

    accepted = await enqueue_platform_fulfillment(
        redis, str(uuid4()), event_id, attempt_count=2
    )

    assert accepted is True
    assert redis.calls[0][1]["_job_id"] == f"platform-fulfillment:{event_id}:2"


@pytest.mark.asyncio
async def test_existing_deterministic_job_is_accepted() -> None:
    accepted = await enqueue_platform_fulfillment(
        ExistingJobRedis(), str(uuid4()), str(uuid4())
    )

    assert accepted is True


@pytest.mark.asyncio
async def test_worker_raises_arq_retry_for_retry_wait() -> None:
    service = SimpleNamespace(
        process=lambda *args: None,
    )

    async def process(*args):
        return SimpleNamespace(
            status="retry_wait", attempt_count=1, retry_after_seconds=30
        )

    service.process = process
    with pytest.raises(Retry):
        await process_platform_fulfillment_job(
            {"platform_fulfillment_service": service}, str(uuid4()), str(uuid4())
        )


@pytest.mark.asyncio
async def test_sweeper_enqueues_due_outbox_records() -> None:
    tenant_id, event_id = uuid4(), uuid4()
    repository = SimpleNamespace()

    async def list_due(**kwargs):
        return [(tenant_id, event_id, 1)]

    repository.list_due = list_due
    redis = FakeRedis()
    service = SimpleNamespace(processing_timeout=object())

    queued = await enqueue_due_platform_fulfillments(
        {
            "platform_fulfillment_service": service,
            "platform_fulfillment_outbox_repository": repository,
            "redis": redis,
        }
    )

    assert queued == 1
    assert redis.calls[0][0][0] == "process_platform_fulfillment_job"


def test_platform_fulfillment_jobs_are_registered_with_worker() -> None:
    assert process_platform_fulfillment_job in WorkerSettings.functions
    assert enqueue_due_platform_fulfillments in WorkerSettings.functions
    assert any(
        job.coroutine is enqueue_due_platform_fulfillments
        for job in WorkerSettings.cron_jobs
    )
