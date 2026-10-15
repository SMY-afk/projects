import asyncio
from datetime import UTC, date, datetime
from types import SimpleNamespace
from uuid import uuid4

from erp_api.services.affiliate_schedule_queries import ScheduledShop
from erp_api.workers import affiliate_live_schedule as schedule
from erp_api.workers.settings import WorkerSettings


def test_live_windows_cover_two_calendar_months_without_gaps() -> None:
    assert schedule.live_windows(date(2026, 10, 3)) == [
        (date(2026, 8, 3), date(2026, 9, 1)),
        (date(2026, 9, 2), date(2026, 10, 1)),
        (date(2026, 10, 2), date(2026, 10, 3)),
    ]


def test_live_queue_is_shop_scoped_waits_for_samples_and_is_idempotent(monkeypatch):
    tenant_id = uuid4()
    first = ScheduledShop(
        tenant_id, uuid4(), "America/Los_Angeles", "USD", "fanfu toy tool"
    )
    second = ScheduledShop(
        tenant_id, uuid4(), "America/Los_Angeles", "USD", "Akeleo-Drive"
    )
    jobs = []

    class Redis:
        def __init__(self):
            self.keys = set()

        async def set(self, key, _value, *, ex, nx):
            assert ex == 86_400 and nx
            if key in self.keys:
                return False
            self.keys.add(key)
            return True

        async def delete(self, key):
            self.keys.discard(key)

        async def enqueue_job(self, name, *args, **kwargs):
            jobs.append((name, args, kwargs))
            return object()

    class Health:
        def __init__(self, _redis):
            pass

        async def get(self, _tenant_id, _shop_id):
            return SimpleNamespace(state="online", session_available=True)

        async def observed_date_for(self, _tenant_id, shop_id, _resource):
            assert _resource == "liveAccounts"
            return date(2026, 10, 3) if shop_id == first.shop_id else date(2026, 10, 1)

    async def sample_ready(_database, _tenant, shop_id, *, now):
        assert now == datetime(2026, 10, 4, 15, 50, tzinfo=UTC)
        return shop_id == first.shop_id

    monkeypatch.setattr(schedule, "AffiliateCaptureHealthRepository", Health)
    monkeypatch.setattr(
        schedule,
        "_active_live_shops",
        lambda _db: asyncio.sleep(0, result=[first, second]),
    )
    monkeypatch.setattr(schedule, "sample_round_releases_affiliate", sample_ready)
    monkeypatch.setattr(
        schedule, "_now", lambda _ctx: datetime(2026, 10, 4, 15, 50, tzinfo=UTC)
    )
    context = {"database": object(), "redis": Redis()}
    assert asyncio.run(schedule.enqueue_scheduled_affiliate_live_syncs(context)) == 3
    assert len(jobs) == 3
    assert all(job[1][1] == str(first.shop_id) and job[1][2] == "live" for job in jobs)
    assert all(job[1][6] == "AFFILIATE_ACCOUNTS" for job in jobs)
    assert all(job[2]["_queue_name"] == "arq:queue" for job in jobs)
    assert asyncio.run(schedule.enqueue_scheduled_affiliate_live_syncs(context)) == 0
    assert schedule.enqueue_scheduled_affiliate_live_syncs in WorkerSettings.functions


def test_live_queue_probes_persisted_day_when_fresh_observation_expires(monkeypatch):
    shop = ScheduledShop(
        uuid4(), uuid4(), "America/Los_Angeles", "USD", "fanfu toy tool"
    )
    jobs = []

    class Redis:
        def __init__(self):
            self.keys = set()

        async def set(self, key, _value, *, ex, nx):
            assert ex == 86_400 and nx
            if key in self.keys:
                return False
            self.keys.add(key)
            return True

        async def delete(self, key):
            self.keys.remove(key)

        async def enqueue_job(self, name, *args, **kwargs):
            jobs.append((name, args, kwargs))
            return object()

    class Health:
        def __init__(self, _redis):
            pass

        async def get(self, _tenant_id, _shop_id):
            return SimpleNamespace(state="online", session_available=True)

        async def observed_date_for(self, _tenant_id, _shop_id, _resource):
            return None

    async def no_recent(*_args, **_kwargs):
        return None

    async def persisted(_database, _tenant_id, _shop_id):
        return date(2026, 10, 5)

    async def sample_ready(*_args, **_kwargs):
        return True

    monkeypatch.setattr(schedule, "AffiliateCaptureHealthRepository", Health)
    monkeypatch.setattr(schedule, "latest_recent_live_observation", no_recent)
    monkeypatch.setattr(schedule, "latest_persisted_live_date", persisted)
    monkeypatch.setattr(schedule, "sample_round_releases_affiliate", sample_ready)
    monkeypatch.setattr(schedule, "_active_live_shops", lambda _db: asyncio.sleep(0, result=[shop]))
    monkeypatch.setattr(schedule, "_now", lambda _ctx: datetime(2026, 10, 7, 16, 10, tzinfo=UTC))
    context = {"database": object(), "redis": Redis()}
    assert asyncio.run(schedule.enqueue_scheduled_affiliate_live_syncs(context)) == 1
    assert asyncio.run(schedule.enqueue_scheduled_affiliate_live_syncs(context)) == 0
    assert len(jobs) == 1
    assert jobs[0][1][2] == "live"
    assert jobs[0][1][6] == "AFFILIATE_ACCOUNTS"
    assert jobs[0][2]["_job_id"].startswith("affiliate:live-probe:")
    assert jobs[0][2]["_queue_name"] == "arq:queue"
