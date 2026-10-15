"""Check ARQ's actual configuration reader, not Python attribute inheritance."""

import asyncio

from arq.worker import create_worker, get_kwargs

from erp_api.workers.order_retry_settings import OrderRetryWorkerSettings
from erp_api.workers.settings import WorkerSettings


def test_order_worker_forwards_the_existing_runtime_config():
    original = get_kwargs(WorkerSettings)
    candidate = get_kwargs(OrderRetryWorkerSettings)
    assert set(candidate) == set(original) | {"job_completion_wait"}
    for key, value in original.items():
        same = candidate[key] == value
        assert same, f"Existing Worker setting changed: {key}"
    assert candidate["job_completion_wait"] == 120


def test_order_worker_can_be_constructed_without_connecting():
    async def construct():
        worker = create_worker(OrderRetryWorkerSettings, handle_signals=False)
        assert worker.functions
        assert worker.cron_jobs
        assert worker._job_completion_wait == 120

    asyncio.run(construct())
