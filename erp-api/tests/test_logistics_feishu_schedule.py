import json
from datetime import datetime
from types import SimpleNamespace

import pytest

from erp_api.workers import logistics_feishu_job as job

CONFIG = {
    "tenantId": "tenant", "tableId": "table", "intervalSeconds": 43200,
    "dailySchedule": {
        "timezone": "Asia/Shanghai", "hours": [0, 12],
        "startAt": "2026-10-14T04:00:00+00:00",
    },
}


def instant(value):
    return datetime.fromisoformat(value)


@pytest.mark.parametrize("now,due,next_run", [
    ("2026-10-14T01:10:00+00:00", None, "2026-10-14T04:00:00+00:00"),
    ("2026-10-14T03:59:59+00:00", None, "2026-10-14T04:00:00+00:00"),
    ("2026-10-14T04:00:00+00:00", "2026-10-14T04:00:00+00:00", "2026-10-14T04:00:00+00:00"),
    ("2026-10-14T16:00:00+00:00", "2026-10-14T16:00:00+00:00", "2026-10-14T16:00:00+00:00"),
    ("2026-10-14T16:02:00+00:00", "2026-10-14T16:00:00+00:00", "2026-10-14T16:00:00+00:00"),
])
def test_runs_only_at_beijing_noon_and_midnight_starting_at_activation(now, due, next_run):
    actual_due, actual_next = job.schedule_window(CONFIG["dailySchedule"], instant(now), {})
    assert actual_due == (instant(due) if due else None)
    assert actual_next == instant(next_run)


def test_successful_slot_survives_restart_and_next_slot_crosses_calendar_day():
    health = {"status": "ok", "scheduledFor": "2026-10-14T16:00:00+00:00"}
    due, next_run = job.schedule_window(CONFIG["dailySchedule"], instant("2026-10-14T16:05:00+00:00"), health)
    assert due is None
    assert next_run == instant("2026-10-15T04:00:00+00:00")


def test_failed_slot_remains_due_for_retry():
    health = {"status": "retrying", "scheduledFor": "2026-10-14T04:00:00+00:00"}
    due, _ = job.schedule_window(CONFIG["dailySchedule"], instant("2026-10-14T04:02:00+00:00"), health)
    assert due == instant("2026-10-14T04:00:00+00:00")


@pytest.mark.parametrize("hours,start", [
    ([0, 24], "2026-10-14T04:00:00+00:00"),
    ([0, 0], "2026-10-14T04:00:00+00:00"),
    ([False, 12], "2026-10-14T04:00:00+00:00"),
    ([0, 12], "2026-10-14T04:01:00+00:00"),
])
def test_invalid_schedule_fails_closed(hours, start):
    schedule = {"timezone": "Asia/Shanghai", "hours": hours, "startAt": start}
    with pytest.raises(ValueError):
        job.schedule_window(schedule, instant("2026-10-14T04:00:00+00:00"), {})


class Redis:
    def __init__(self, health=None, competing_health=None):
        self.values = {job.HEALTH_KEY: json.dumps(health or {})}
        self.competing_health = competing_health
        self.lock_attempts = 0
        self.releases = 0

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, **kwargs):
        if kwargs.get("nx"):
            self.lock_attempts += 1
            if self.competing_health:
                self.values[job.HEALTH_KEY] = json.dumps(self.competing_health)
        self.values[key] = value
        return True

    async def eval(self, script, count, key, owner):
        self.releases += 1
        if self.values.get(key) == owner:
            self.values.pop(key)


@pytest.mark.asyncio
async def test_waiting_does_not_acquire_lock_or_publish(monkeypatch):
    redis = Redis()
    async def forbidden(*args, **kwargs):
        pytest.fail("Waiting for noon must not publish")
    monkeypatch.setattr(job, "sync_once", forbidden)
    delay = await job.sync_cycle(SimpleNamespace(redis=redis), None, None, CONFIG,
                                 now=instant("2026-10-14T03:59:59+00:00"))
    assert delay == 1
    assert redis.lock_attempts == 0


@pytest.mark.asyncio
async def test_due_slot_publishes_once_and_restart_skips_it(monkeypatch):
    redis, calls = Redis(), []
    async def publish(*args, **kwargs):
        calls.append(kwargs)
        return {"readbackVerified": True, "created": 0, "updated": 3}
    monkeypatch.setattr(job, "sync_once", publish)
    state = SimpleNamespace(redis=redis)
    now = instant("2026-10-14T04:00:00+00:00")
    await job.sync_cycle(state, None, None, CONFIG, now=now)
    await job.sync_cycle(state, None, None, CONFIG, now=now)
    health = json.loads(redis.values[job.HEALTH_KEY])
    assert len(calls) == 1 and calls[0]["apply"] is True
    assert health["scheduledFor"] == now.isoformat()
    assert health["nextScheduledFor"] == "2026-10-14T16:00:00+00:00"
    assert health["readbackVerified"] is True
    assert redis.releases == 1


@pytest.mark.asyncio
async def test_slot_is_rechecked_after_lock_to_avoid_duplicate_publish(monkeypatch):
    redis = Redis(competing_health={"status": "ok", "scheduledFor": "2026-10-14T04:00:00+00:00"})
    async def forbidden(*args, **kwargs):
        pytest.fail("Another worker already completed this slot")
    monkeypatch.setattr(job, "sync_once", forbidden)
    await job.sync_cycle(SimpleNamespace(redis=redis), None, None, CONFIG,
                         now=instant("2026-10-14T04:00:00+00:00"))
    assert redis.lock_attempts == redis.releases == 1


@pytest.mark.asyncio
async def test_source_failure_releases_lock_without_marking_slot_complete(monkeypatch):
    redis = Redis()
    async def fail(*args, **kwargs):
        raise ValueError("Logistics monitor source is stale")
    monkeypatch.setattr(job, "sync_once", fail)
    with pytest.raises(ValueError, match="stale"):
        await job.sync_cycle(SimpleNamespace(redis=redis), None, None, CONFIG,
                             now=instant("2026-10-14T04:00:00+00:00"))
    assert redis.releases == 1
    assert "scheduledFor" not in json.loads(redis.values[job.HEALTH_KEY])
