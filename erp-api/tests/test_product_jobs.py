import asyncio
from types import SimpleNamespace
from uuid import uuid4

from erp_api.workers.product_jobs import (
    enqueue_scheduled_product_syncs,
    sync_product_job,
)
from erp_api.workers.settings import WorkerSettings


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
    async def scalars(self, statement):
        return FakeScalars([uuid4()])


class FakeDatabase:
    def __init__(self) -> None:
        self.system_session_factory = lambda: FakeSystemSession()

    async def session(self, tenant_id):
        yield FakeShopSession()


class FakeRedis:
    def __init__(self) -> None:
        self.jobs = []

    async def enqueue_job(self, *args, **kwargs):
        self.jobs.append((args, kwargs))


class FakeProductSyncService:
    def __init__(self) -> None:
        self.calls = []

    async def sync_products(self, tenant_id, *, shop_id):
        self.calls.append((tenant_id, shop_id))
        return SimpleNamespace(status="succeeded")


def test_product_sync_job_calls_official_product_service() -> None:
    service = FakeProductSyncService()
    tenant_id = uuid4()
    shop_id = uuid4()

    result = asyncio.run(
        sync_product_job(
            {"product_sync_service": service}, str(tenant_id), str(shop_id)
        )
    )

    assert result.status == "succeeded"
    assert service.calls == [(tenant_id, shop_id)]


def test_scheduled_product_jobs_are_deduplicated_per_shop() -> None:
    redis = FakeRedis()

    queued = asyncio.run(
        enqueue_scheduled_product_syncs({"database": FakeDatabase(), "redis": redis})
    )

    assert queued == 1
    assert redis.jobs[0][0][0] == "sync_product_job"
    assert redis.jobs[0][1]["_job_id"].startswith("product-sync:")


def test_product_worker_allows_time_for_cursor_resume_retries() -> None:
    registered = next(
        function
        for function in WorkerSettings.functions
        if getattr(function, "coroutine", None) is sync_product_job
    )

    assert registered.timeout_s == 900
