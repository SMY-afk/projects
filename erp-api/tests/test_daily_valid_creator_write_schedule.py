"""The 01:30 writer is separate from the 23:30 source collector schedule."""

from datetime import UTC, date, datetime
from fnmatch import fnmatch

import pytest

from erp_api.workers import daily_valid_creator_jobs as jobs
from scripts import daily_valid_creator_batch as batch
from scripts import daily_valid_creator_pipeline as pipeline
from scripts import daily_valid_creator_report_gate as reports


class Redis:
    def __init__(self):
        self.values = {}
        self.queued = []

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, *, nx=False, ex=None):
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    async def scan_iter(self, *, match, count):
        for key in list(self.values):
            if fnmatch(key, match):
                yield key

    async def eval(self, _, count, key, owner):
        if self.values.get(key) == owner:
            self.values.pop(key)

    async def enqueue_job(self, name, *args, **kwargs):
        self.queued.append((name, args, kwargs))
        return object()


@pytest.fixture
def state(monkeypatch):
    value = {"redis": Redis(), "snapshot_calls": 0, "writes": 0,
             "now": datetime(2026, 10, 14, 15, 50, tzinfo=UTC)}
    value["ctx"] = {"database": object(), "redis": value["redis"]}

    async def snapshot(*_):
        value["snapshot_calls"] += 1
        return {}, {}, "new-fingerprint"

    async def complete(*_):
        return {}

    async def runs(*_):
        return []

    async def reconcile(*_, **kwargs):
        assert kwargs["scheduled_update"] is True
        value["writes"] += 1
        return {"apply": {"status": "verified", "second_preview": [0, 0, 0]}}

    monkeypatch.setattr(jobs, "_now", lambda _: value["now"])
    monkeypatch.setattr(jobs, "_ready_snapshot", snapshot)
    monkeypatch.setattr(batch, "load_batch_runs", runs)
    monkeypatch.setattr(batch, "evaluate_batch", lambda *_: {})
    monkeypatch.setattr(reports, "missing_creator_reports", complete)
    monkeypatch.setattr(pipeline, "reconcile", reconcile)
    return value


@pytest.mark.asyncio
async def test_2350_keeps_previous_source_batch_until_0130(state):
    assert await jobs.enqueue_due_valid_creator_syncs(state["ctx"]) == 1
    assert state["redis"].queued[0][1][0] == "2026-10-13"


@pytest.mark.asyncio
async def test_0130_switches_to_previous_calendar_day_source_batch(state):
    state["now"] = datetime(2026, 10, 14, 17, 30, tzinfo=UTC)
    assert await jobs.enqueue_due_valid_creator_syncs(state["ctx"]) == 1
    assert state["redis"].queued[0][1][0] == "2026-10-14"


@pytest.mark.asyncio
async def test_completed_day_skips_new_fingerprint_without_source_reads(state):
    state["redis"].values["valid-creator-sync:20261013:older-fingerprint:success"] = "1"
    assert await jobs.enqueue_due_valid_creator_syncs(state["ctx"]) == 0
    result = await jobs.sync_daily_valid_creator_job(
        state["ctx"], "2026-10-13", "new-fingerprint", "owner")
    assert result["status"] == "already_verified"
    assert state["snapshot_calls"] == state["writes"] == 0


@pytest.mark.asyncio
async def test_revoked_receipt_does_not_block_due_update(state):
    state["redis"].values["valid-creator-sync:20261013:old:success_revoked_incomplete_view"] = "1"
    assert await jobs.enqueue_due_valid_creator_syncs(state["ctx"]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["revoked", "0", ""])
async def test_non_success_receipt_value_does_not_skip_due_update(state, value):
    state["redis"].values["valid-creator-sync:20261013:new-fingerprint:success"] = value
    assert await jobs.enqueue_due_valid_creator_syncs(state["ctx"]) == 1


@pytest.mark.asyncio
async def test_superseded_queued_batch_does_no_source_or_feishu_work(state):
    lock = "valid-creator-sync:20261012:old-fingerprint:lock"
    state["redis"].values[lock] = "owner"
    result = await jobs.sync_daily_valid_creator_job(
        state["ctx"], "2026-10-12", "old-fingerprint", "owner")
    assert result["status"] == "superseded"
    assert state["snapshot_calls"] == state["writes"] == 0
    assert lock not in state["redis"].values


@pytest.mark.asyncio
async def test_due_job_passes_scheduled_write_guard_to_pipeline(state):
    result = await jobs.sync_daily_valid_creator_job(
        state["ctx"], "2026-10-13", "new-fingerprint", "owner")
    assert result["status"] == "verified"
    assert state["writes"] == 1


def test_shared_collection_clock_stays_2330():
    from erp_api.services.affiliate_schedule_queries import (
        DAILY_RUN_TIME,
        latest_due_schedule_date,
    )

    assert str(DAILY_RUN_TIME) == "23:30:00"
    assert latest_due_schedule_date(datetime(2026, 10, 14, 15, 50, tzinfo=UTC)) == date(2026, 10, 14)
