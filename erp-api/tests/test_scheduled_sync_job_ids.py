import asyncio
from datetime import UTC, datetime
from uuid import uuid4

from erp_api.workers.order_jobs import (
    enqueue_scheduled_order_syncs,
    scheduled_order_job_id,
)
from erp_api.workers.product_jobs import (
    enqueue_scheduled_product_syncs,
    scheduled_product_job_id,
)


class FakeScalars:
    def __init__(self, values) -> None:
        self._values = values

    def all(self):
        return self._values


class FakeSystemSession:
    def __init__(self, tenant_id) -> None:
        self._tenant_id = tenant_id

    async def scalars(self, statement):
        return FakeScalars([self._tenant_id])

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None


class FakeShopSession:
    def __init__(self, shop_id) -> None:
        self._shop_id = shop_id

    async def scalars(self, statement):
        return FakeScalars([self._shop_id])


class FakeDatabase:
    def __init__(self, tenant_id, shop_id) -> None:
        self.system_session_factory = lambda: FakeSystemSession(tenant_id)
        self._shop_id = shop_id

    async def session(self, tenant_id):
        yield FakeShopSession(self._shop_id)


class FakeRedis:
    def __init__(self) -> None:
        self.jobs = []

    async def enqueue_job(self, *args, **kwargs):
        self.jobs.append((args, kwargs))


def test_order_job_id_changes_only_between_ten_minute_slots() -> None:
    tenant_id = uuid4()
    shop_id = uuid4()

    first = scheduled_order_job_id(
        tenant_id, shop_id, datetime(2026, 9, 3, 2, 9, 59, tzinfo=UTC)
    )
    same_slot = scheduled_order_job_id(
        tenant_id, shop_id, datetime(2026, 9, 3, 2, 0, tzinfo=UTC)
    )
    next_slot = scheduled_order_job_id(
        tenant_id, shop_id, datetime(2026, 9, 3, 2, 10, tzinfo=UTC)
    )

    assert first == same_slot
    assert first.endswith(":202609030200")
    assert next_slot.endswith(":202609030210")
    assert next_slot != first


def test_product_job_id_changes_only_between_hour_slots() -> None:
    tenant_id = uuid4()
    shop_id = uuid4()

    first = scheduled_product_job_id(
        tenant_id, shop_id, datetime(2026, 9, 3, 2, 59, 59, tzinfo=UTC)
    )
    same_slot = scheduled_product_job_id(
        tenant_id, shop_id, datetime(2026, 9, 3, 2, 0, tzinfo=UTC)
    )
    next_slot = scheduled_product_job_id(
        tenant_id, shop_id, datetime(2026, 9, 3, 3, 0, tzinfo=UTC)
    )

    assert first == same_slot
    assert first.endswith(":2026090302")
    assert next_slot.endswith(":2026090303")
    assert next_slot != first


def test_schedulers_enqueue_jobs_with_the_current_time_slot() -> None:
    tenant_id = uuid4()
    shop_id = uuid4()
    database = FakeDatabase(tenant_id, shop_id)
    now = datetime(2026, 9, 3, 2, 17, tzinfo=UTC)

    order_redis = FakeRedis()
    product_redis = FakeRedis()
    order_count = asyncio.run(
        enqueue_scheduled_order_syncs(
            {"database": database, "redis": order_redis, "clock": lambda: now}
        )
    )
    product_count = asyncio.run(
        enqueue_scheduled_product_syncs(
            {"database": database, "redis": product_redis, "clock": lambda: now}
        )
    )

    assert order_count == product_count == 1
    assert order_redis.jobs[0][1]["_job_id"] == (
        f"order-sync:{tenant_id}:{shop_id}:202609030210"
    )
    assert product_redis.jobs[0][1]["_job_id"] == (
        f"product-sync:{tenant_id}:{shop_id}:2026090302"
    )
