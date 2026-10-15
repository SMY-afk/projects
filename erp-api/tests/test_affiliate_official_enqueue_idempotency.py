import asyncio
from datetime import date
from uuid import uuid4

from erp_api.services.affiliate_center_contract import (
    AffiliateCenterQuery,
    AffiliateCenterResource,
)
from erp_api.services.affiliate_official_enqueue import enqueue_official_queries


class FakeSyncRepository:
    def __init__(self) -> None:
        self.runs = {}
        self.cancelled = []

    async def create_run(self, tenant_id, shop_id, **kwargs):
        job_id = kwargs['job_id']
        self.runs.setdefault(job_id, uuid4())
        return self.runs[job_id]

    async def cancel_run(self, tenant_id, run_id):
        self.cancelled.append((tenant_id, run_id))


class FakeQueue:
    def __init__(self) -> None:
        self.job_ids = set()

    async def enqueue_job(self, *args, **kwargs):
        job_id = kwargs['_job_id']
        if job_id in self.job_ids:
            return None
        self.job_ids.add(job_id)
        return object()


def test_rapid_official_requests_reuse_the_same_window_job() -> None:
    tenant_id = uuid4()
    repository = FakeSyncRepository()
    queue = FakeQueue()
    query = AffiliateCenterQuery(
        resource=AffiliateCenterResource.VIDEOS,
        shop_id=uuid4(),
        window_start=date(2026, 8, 3),
        window_end=date(2026, 9, 1),
        shop_timezone='America/Los_Angeles',
        currency='USD',
        filters={},
    )

    first = asyncio.run(
        enqueue_official_queries(queue, repository, tenant_id, [query])
    )
    second = asyncio.run(
        enqueue_official_queries(queue, repository, tenant_id, [query])
    )

    assert first['items'][0]['runId'] == second['items'][0]['runId']
    assert first['items'][0]['existing'] is False
    assert second['items'][0]['existing'] is True
    assert repository.cancelled == []
    assert len(queue.job_ids) == 1
