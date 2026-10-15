"""Retry indefinitely with cooldowns; preserve old attempt/grant audit keys."""

from datetime import UTC, datetime
from fnmatch import fnmatch

import pytest

from erp_api.workers import daily_valid_creator_jobs as jobs
from scripts import daily_valid_creator_batch as batch
from scripts import daily_valid_creator_pipeline as pipeline
from scripts import daily_valid_creator_report_gate as reports

BATCH = "valid-creator-sync:20261013"


class Redis:
    def __init__(self):
        self.values = {BATCH + ":attempts": "900"}
        for suffix in ("authorized_extra_attempt", "authorized_scope_repair_attempt",
                       "authorized_full_history_refresh_attempt"):
            self.values[BATCH + ":" + suffix] = "invalid-retained-audit-value"
        self.expirations = {}
        self.queued = []

    async def get(self, key):
        assert not key.endswith(":attempts") and ":authorized_" not in key
        return self.values.get(key)

    async def scan_iter(self, *, match, count):
        for key in self.values:
            if fnmatch(key, match):
                yield key

    async def set(self, key, value, *, nx=False, ex=None):
        assert not key.endswith(":attempts") and ":authorized_" not in key
        if nx and key in self.values:
            return False
        self.values[key] = value
        self.expirations[key] = ex
        return True

    async def incr(self, _):
        pytest.fail("The daily full sync must no longer count attempts")

    async def expire(self, *_):
        pytest.fail("Historical attempt counter TTL must remain untouched")

    async def eval(self, _, count, key, owner):
        assert count == 1 and key.endswith(":lock")
        if self.values.get(key) == owner:
            del self.values[key]

    async def enqueue_job(self, name, *args, **kwargs):
        self.queued.append((name, args, kwargs))
        return object()


@pytest.fixture
def unbounded(monkeypatch):
    redis = Redis()
    state = {"redis": redis, "ctx": {"redis": redis, "database": object()},
             "fingerprint": "fingerprint", "mode": "success", "calls": 0}
    state["historical"] = dict(redis.values)

    async def snapshot(*_):
        if state["mode"] == "stale":
            return None
        return {}, {}, state["fingerprint"]

    async def complete(*_):
        return {"shop": [{}]} if state["mode"] == "reports" else {}

    async def runs(*_):
        return []

    def evaluate(*_):
        if state["mode"] == "batch":
            raise ValueError("Incomplete batch")
        return {"required_windows": 45}

    async def reconcile(*_, **kwargs):
        state["calls"] += 1
        assert kwargs["apply"] is True and kwargs["refresh_history"] is True
        assert "backup_directory" in kwargs
        if state["mode"] == "failed":
            raise RuntimeError("Feishu read failed")
        return {"apply": {"status": "verified", "second_preview": [0, 0, 0]}}

    monkeypatch.setattr(jobs, "_now", lambda _: datetime(2026, 10, 14, 3, tzinfo=UTC))
    monkeypatch.setattr(jobs, "_ready_snapshot", snapshot)
    monkeypatch.setattr(batch, "load_batch_runs", runs)
    monkeypatch.setattr(batch, "evaluate_batch", evaluate)
    monkeypatch.setattr(reports, "missing_creator_reports", complete)
    monkeypatch.setattr(pipeline, "reconcile", reconcile)
    return state


def assert_historical_keys_unchanged(state):
    assert {key: state["redis"].values[key] for key in state["historical"]} == state["historical"]


@pytest.mark.asyncio
async def test_old_exhausted_counters_and_grants_do_not_block_or_increment(unbounded):
    state = unbounded
    assert await jobs.enqueue_due_valid_creator_syncs(state["ctx"]) == 1
    result = await jobs.sync_daily_valid_creator_job(state["ctx"], *state["redis"].queued[-1][1])
    assert result["status"] == "verified"
    assert state["calls"] == 1
    assert await jobs.enqueue_due_valid_creator_syncs(state["ctx"]) == 0
    assert_historical_keys_unchanged(state)


@pytest.mark.asyncio
async def test_more_than_four_failures_retry_after_fixed_batch_cooldown(unbounded):
    state = unbounded
    state["mode"] = "failed"
    redis = state["redis"]
    for index in range(8):
        state["fingerprint"] = f"fingerprint-{index}"
        assert await jobs.enqueue_due_valid_creator_syncs(state["ctx"]) == 1
        args = redis.queued[-1][1]
        with pytest.raises(RuntimeError, match="Feishu read failed"):
            await jobs.sync_daily_valid_creator_job(state["ctx"], *args)
        assert redis.expirations[BATCH + ":cooldown"] == 900
        assert redis.expirations[BATCH + f":fingerprint-{index}:cooldown"] == 900
        assert_historical_keys_unchanged(state)
        state["fingerprint"] = "new-fingerprint-during-cooldown"
        assert await jobs.enqueue_due_valid_creator_syncs(state["ctx"]) == 0
        deferred = await jobs.sync_daily_valid_creator_job(
            state["ctx"], "2026-10-13", state["fingerprint"], "owner")
        assert deferred["status"] == "retry_deferred"
        assert state["calls"] == index + 1
        redis.values.pop(BATCH + ":cooldown")
    assert len(redis.queued) == state["calls"] == 8


@pytest.mark.asyncio
async def test_existing_success_skips_even_directly_queued_duplicate_read(unbounded):
    state = unbounded
    state["redis"].values[BATCH + ":fingerprint:success"] = "1"
    assert await jobs.enqueue_due_valid_creator_syncs(state["ctx"]) == 0
    result = await jobs.sync_daily_valid_creator_job(
        state["ctx"], "2026-10-13", "fingerprint", "owner")
    assert result["status"] == "already_verified"
    assert state["calls"] == 0
    assert_historical_keys_unchanged(state)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["stale", "reports", "batch"])
async def test_source_not_ready_defers_for_300_seconds_without_feishu_read(unbounded, mode):
    state = unbounded
    state["mode"] = mode
    assert await jobs.enqueue_due_valid_creator_syncs(state["ctx"]) == 0
    assert state["redis"].expirations[BATCH + ":cooldown"] == 300
    assert state["calls"] == 0
    assert_historical_keys_unchanged(state)


@pytest.mark.asyncio
async def test_missing_reports_queued_job_sets_pre_read_cooldown(unbounded):
    state = unbounded
    state["mode"] = "reports"
    result = await jobs.sync_daily_valid_creator_job(
        state["ctx"], "2026-10-13", "fingerprint", "owner")
    assert result["status"] == "source_not_ready"
    assert state["redis"].expirations[BATCH + ":cooldown"] == 300
    assert state["calls"] == 0
    assert_historical_keys_unchanged(state)


@pytest.mark.asyncio
async def test_stale_queued_job_sets_pre_read_batch_and_fingerprint_cooldown(unbounded):
    state = unbounded
    state["mode"] = "stale"
    with pytest.raises(RuntimeError, match="Direct TK dates changed"):
        await jobs.sync_daily_valid_creator_job(
            state["ctx"], "2026-10-13", "fingerprint", "owner")
    assert state["redis"].expirations[BATCH + ":cooldown"] == 300
    assert state["redis"].expirations[BATCH + ":fingerprint:cooldown"] == 300
    assert state["calls"] == 0
    assert_historical_keys_unchanged(state)


@pytest.mark.asyncio
async def test_release_lock_never_removes_another_owners_lock(unbounded):
    state = unbounded
    state["redis"].values[BATCH + ":fingerprint:success"] = "1"
    lock = BATCH + ":fingerprint:lock"
    state["redis"].values[lock] = "different-owner"
    await jobs.sync_daily_valid_creator_job(state["ctx"], "2026-10-13", "fingerprint", "owner")
    assert state["redis"].values[lock] == "different-owner"
