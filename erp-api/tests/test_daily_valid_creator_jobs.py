from datetime import UTC, date, datetime
from fnmatch import fnmatch
from types import SimpleNamespace
from uuid import uuid4

import pytest

from erp_api.workers import daily_valid_creator_jobs as jobs
from erp_api.workers.daily_valid_creator_settings import (
    DailyValidCreatorWorkerSettings,
)
from scripts import daily_valid_creator_batch as batch
from scripts import daily_valid_creator_pipeline as pipeline
from scripts import daily_valid_creator_report_gate as report_gate
from scripts.daily_valid_creator_core import SHOP_LINES


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.expirations = {}
        self.queued = []

    async def get(self, key):
        return self.values.get(key)

    async def scan_iter(self, *, match, count):
        for key in self.values:
            if fnmatch(key, match):
                yield key

    async def set(self, key, value, *, nx=False, ex=None):
        if nx and key in self.values:
            return False
        self.values[key] = value
        if ex is not None:
            self.expirations[key] = ex
        return True

    async def eval(self, _script, _count, key, owner):
        if self.values.get(key) == owner:
            del self.values[key]
            return 1
        return 0

    async def enqueue_job(self, name, *args, **kwargs):
        self.queued.append((name, args, kwargs))
        return object()


@pytest.fixture(autouse=True)
def legacy_job_clock(monkeypatch):
    monkeypatch.setattr(jobs, "_now", lambda _: datetime(2026, 10, 5, 6, tzinfo=UTC))


def test_isolated_worker_registers_capture_and_reconcile_crons() -> None:
    worker = DailyValidCreatorWorkerSettings
    assert worker.queue_name == jobs.QUEUE_NAME
    assert worker.max_jobs == 1
    names = {entry.name for entry in worker.cron_jobs}
    assert names == {
        "cron:enqueue_due_valid_creator_syncs",
        "cron:enqueue_scheduled_affiliate_creator_syncs",
        "cron:enqueue_scheduled_affiliate_video_syncs",
        "cron:enqueue_scheduled_affiliate_live_syncs",
    }
    job_ids = [entry.job_id for entry in worker.cron_jobs if entry.job_id]
    assert len(job_ids) == len(set(job_ids)) == 3


@pytest.mark.asyncio
async def test_completion_scan_queues_once_and_job_marks_verified(monkeypatch) -> None:
    cutoffs = {
        name: {
            "creators": date(2026, 10, 3),
            "videos": date(2026, 10, 1),
            "liveAccounts": date(2026, 10, 2),
        }
        for name in SHOP_LINES
    }
    redis = FakeRedis()
    ctx = {"redis": redis, "database": object()}
    now = datetime(2026, 10, 5, 6, tzinfo=UTC)

    async def snapshot(*_):
        return cutoffs, {"source": "direct_tk_sources"}, "fingerprint"

    async def runs(*_):
        return []

    async def reconcile(*_, **kwargs):
        assert kwargs["apply"] is True
        return {"apply": {"status": "verified", "second_preview": [0, 0, 0]}}

    async def complete_reports(*_):
        return {}

    monkeypatch.setattr(jobs, "_now", lambda *_: now)
    monkeypatch.setattr(jobs, "_ready_snapshot", snapshot)
    monkeypatch.setattr(batch, "load_batch_runs", runs)
    monkeypatch.setattr(batch, "evaluate_batch", lambda *_: {})
    monkeypatch.setattr(pipeline, "reconcile", reconcile)
    monkeypatch.setattr(report_gate, "missing_creator_reports", complete_reports)
    assert await jobs.enqueue_due_valid_creator_syncs(ctx) == 1
    assert await jobs.enqueue_due_valid_creator_syncs(ctx) == 0
    name, args, _ = redis.queued[0]
    assert name == "sync_daily_valid_creator_job"
    result = await jobs.sync_daily_valid_creator_job(ctx, *args)
    assert result["second_preview"] == [0, 0, 0]
    assert await jobs.enqueue_due_valid_creator_syncs(ctx) == 0


@pytest.mark.asyncio
async def test_incomplete_batch_never_enqueues_sync(monkeypatch) -> None:
    redis = FakeRedis()
    ctx = {"redis": redis}

    async def snapshot(*_):
        return {}, {}, "fingerprint"

    async def runs(*_):
        return []

    def blocked(*_):
        raise ValueError("missing window")

    monkeypatch.setattr(jobs, "_ready_snapshot", snapshot)
    monkeypatch.setattr(batch, "load_batch_runs", runs)
    monkeypatch.setattr(batch, "evaluate_batch", blocked)
    assert await jobs.enqueue_due_valid_creator_syncs(ctx) == 0
    assert redis.queued == []


@pytest.mark.asyncio
async def test_missing_exact_creator_reports_never_queue_or_consume_attempt(monkeypatch) -> None:
    redis = FakeRedis()
    ctx = {"redis": redis, "database": object()}

    async def snapshot(*_):
        return {"跨境4": {"creators": date(2026, 10, 8)}}, {}, "fingerprint"

    async def runs(*_):
        return []

    async def incomplete_reports(*_):
        return {"跨境4": [{"start": "2026-08-08", "end": "2026-09-06"}]}

    async def unexpected_reconcile(*_, **__):
        pytest.fail("Missing reports must not call Feishu")

    monkeypatch.setattr(jobs, "_ready_snapshot", snapshot)
    monkeypatch.setattr(batch, "load_batch_runs", runs)
    monkeypatch.setattr(batch, "evaluate_batch", lambda *_: {})
    monkeypatch.setattr(report_gate, "missing_creator_reports", incomplete_reports)
    monkeypatch.setattr(pipeline, "reconcile", unexpected_reconcile)
    assert await jobs.enqueue_due_valid_creator_syncs(ctx) == 0
    assert redis.queued == []
    redis.values.pop("valid-creator-sync:20261004:cooldown")
    redis.values.pop("valid-creator-sync:20261004:fingerprint:cooldown")
    result = await jobs.sync_daily_valid_creator_job(
        ctx, "2026-10-04", "fingerprint", "owner"
    )
    assert result["status"] == "source_not_ready"
    assert "valid-creator-sync:20261004:attempts" not in redis.values


@pytest.mark.asyncio
async def test_stale_online_evidence_does_not_consume_feishu_attempt(
    monkeypatch,
) -> None:
    redis = FakeRedis()

    async def snapshot(*_):
        return None

    async def unexpected_reconcile(*_, **__):
        pytest.fail("Stale online evidence must not call Feishu")

    monkeypatch.setattr(jobs, "_ready_snapshot", snapshot)
    monkeypatch.setattr(pipeline, "reconcile", unexpected_reconcile)
    with pytest.raises(RuntimeError, match="Direct TK dates changed"):
        await jobs.sync_daily_valid_creator_job(
            {"redis": redis}, "2026-10-04", "fingerprint", "owner"
        )
    assert "valid-creator-sync:20261004:attempts" not in redis.values


@pytest.mark.asyncio
async def test_snapshot_uses_real_resource_observation_timestamps(monkeypatch) -> None:
    observed_creators = datetime(2026, 10, 5, 5, 51, tzinfo=UTC)
    observed_videos = datetime(2026, 10, 5, 5, 55, tzinfo=UTC)
    observed_live = datetime(2026, 10, 5, 5, 53, tzinfo=UTC)
    live_enabled = [True]
    tenant_id = uuid4()
    names = (
        "fanfu toy tool",
        "Akeleo-Drive",
        "Akeleo Fun Toys",
        "NEOPUP",
        "Akeleo Toys",
    )

    async def active_shops(_database):
        return [
            SimpleNamespace(tenant_id=tenant_id, shop_id=uuid4(), source_name=name)
            for name in names
        ]

    class Health:
        async def get(self, *_):
            return SimpleNamespace(state="online", session_available=True)

        async def observed_evidence_for(self, _tenant, _shop, resource, *, now):
            del now
            if resource == "creators":
                return date(2026, 10, 3), observed_creators
            if resource == "videos":
                return date(2026, 10, 1), observed_videos
            return (date(2026, 10, 2), observed_live) if live_enabled[0] else None

    monkeypatch.setattr(jobs, "_active_live_shops", active_shops)
    monkeypatch.setattr(
        jobs,
        "get_settings",
        lambda: SimpleNamespace(affiliate_export_tenant_id=tenant_id),
    )
    monkeypatch.setattr(jobs, "AffiliateCaptureHealthRepository", lambda _: Health())
    snapshot = await jobs._ready_snapshot(
        {"database": object(), "redis": FakeRedis()},
        datetime(2026, 10, 5, 6, tzinfo=UTC),
    )
    assert snapshot is not None
    cutoffs, evidence, _ = snapshot
    assert len(cutoffs) == 5
    monkeypatch.setattr(jobs, "SYNC_RULE_VERSION", "different-rule", raising=False)
    revised = await jobs._ready_snapshot(
        {"database": object(), "redis": FakeRedis()},
        datetime(2026, 10, 5, 6, tzinfo=UTC),
    )
    assert revised is not None and revised[2] != snapshot[2]
    assert {row["observed_at"] for row in evidence["shops"]} == {
        observed_creators.isoformat()
    }
    assert {row["liveAccounts"] for row in evidence["shops"]} == {"2026-10-02"}
    live_enabled[0] = False

    async def recent_live(*_, **__):
        return date(2026, 10, 2), observed_live

    monkeypatch.setattr(jobs, "latest_recent_live_observation", recent_live)
    fallback = await jobs._ready_snapshot(
        {"database": object(), "redis": FakeRedis()},
        datetime(2026, 10, 5, 6, tzinfo=UTC),
    )
    assert fallback is not None and fallback[0] == cutoffs

    async def no_recent_live(*_, **__):
        return None

    monkeypatch.setattr(jobs, "latest_recent_live_observation", no_recent_live)
    assert (
        await jobs._ready_snapshot(
            {"database": object(), "redis": FakeRedis()},
            datetime(2026, 10, 5, 6, tzinfo=UTC),
        )
        is None
    )
