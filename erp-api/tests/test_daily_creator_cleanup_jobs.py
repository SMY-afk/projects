"""Explicit one-time cleanup grants never affect scheduled retries or receipts."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from erp_api.workers import daily_valid_creator_cleanup_jobs as jobs
from erp_api.workers.daily_valid_creator_sync_settings import (
    DailyValidCreatorSyncWorkerSettings,
)
from scripts import daily_valid_creator_cleanup_pipeline as pipeline
from scripts.daily_valid_creator_cleanup_writer import CleanupAuditRequired


class Redis:
    def __init__(self):
        self.values = {"valid-creator-sync:20261013:attempts": "7",
                       "valid-creator-sync:20261013:old:success": "1"}

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, *, nx=False, ex=None):
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True


@pytest.fixture
def authorized(monkeypatch):
    owner = "a" * 32
    redis = Redis()
    grant = {"owner": owner, "scope": jobs.CLEANUP_SCOPE, "mode": "preview",
             "excluded_accounts": ["yana_ok1"]}
    redis.values[jobs.grant_key(owner)] = json.dumps(grant)
    calls = []

    async def cleanup(*_, **kwargs):
        calls.append(kwargs)
        result = {"preview": {"hash": "b" * 64}, "backup": {"records": 10}}
        if kwargs["apply"]:
            result["apply"] = {"status": "verified", "deleted": 2}
        return result

    monkeypatch.setattr(pipeline, "cleanup", cleanup)
    return redis, owner, grant, calls


@pytest.mark.asyncio
async def test_missing_grant_rejects_before_read(monkeypatch):
    async def forbidden(*_, **__):
        pytest.fail("Missing grant cannot read Feishu")

    monkeypatch.setattr(pipeline, "cleanup", forbidden)
    with pytest.raises(ValueError, match="grant"):
        await jobs.cleanup_daily_valid_creators_job({"redis": Redis()}, "a" * 32)


@pytest.mark.asyncio
@pytest.mark.parametrize("field, value", [
    ("scope", "all-history"), ("owner", "wrong"),
    ("excluded_accounts", []), ("mode", "apply"),
])
async def test_malformed_scope_or_exclusion_rejected(authorized, field, value):
    redis, owner, grant, calls = authorized
    grant[field] = value
    redis.values[jobs.grant_key(owner)] = json.dumps(grant)
    with pytest.raises(ValueError, match="grant"):
        await jobs.cleanup_daily_valid_creators_job({"redis": redis}, owner)
    assert calls == []


@pytest.mark.asyncio
async def test_preview_then_frozen_hash_apply_only_once_preserves_retry_history(authorized):
    redis, owner, grant, calls = authorized
    original = deepcopy(redis.values)
    ctx = {"redis": redis}
    preview = await jobs.cleanup_daily_valid_creators_job(ctx, owner)
    assert preview["preview"]["hash"] == "b" * 64
    grant.update(mode="apply", expected_plan_hash=preview["preview"]["hash"])
    redis.values[jobs.grant_key(owner)] = json.dumps(grant)
    result = await jobs.cleanup_daily_valid_creators_job(ctx, owner, apply=True)
    assert result["apply"]["deleted"] == 2
    assert calls[-1]["expected_hash"] == "b" * 64
    assert calls[-1]["excluded_accounts"] == frozenset({"yana_ok1"})
    assert await jobs.cleanup_daily_valid_creators_job(ctx, owner, apply=True) == {
        "status": "already_claimed"}
    assert len(calls) == 2
    for key, value in original.items():
        if key.startswith("valid-creator-sync:"):
            assert redis.values[key] == value


@pytest.mark.asyncio
async def test_apply_grant_hash_required(authorized):
    redis, owner, grant, calls = authorized
    grant["mode"] = "apply"
    redis.values[jobs.grant_key(owner)] = json.dumps(grant)
    with pytest.raises(ValueError, match="hash"):
        await jobs.cleanup_daily_valid_creators_job({"redis": redis}, owner, apply=True)
    assert calls == []


def test_cleanup_registered_only_as_explicit_single_try_serial_job():
    settings = DailyValidCreatorSyncWorkerSettings
    registered = [entry for entry in settings.functions
                  if getattr(entry, "name", "") == "cleanup_daily_valid_creators_job"]
    assert len(registered) == 1
    assert registered[0].max_tries == 1
    assert settings.max_jobs == 1
    assert all("cleanup" not in entry.name for entry in settings.cron_jobs)


@pytest.mark.asyncio
async def test_partial_cleanup_failure_preserves_audit_and_never_replays(authorized, monkeypatch):
    redis, owner, grant, calls = authorized
    grant.update(mode="apply", expected_plan_hash="b" * 64)
    redis.values[jobs.grant_key(owner)] = json.dumps(grant)

    async def fail(*_, **__):
        calls.append("partial")
        raise CleanupAuditRequired(Path("/private/cleanup-audit.json"), ["already-removed"])

    monkeypatch.setattr(pipeline, "cleanup", fail)
    ctx = {"redis": redis}
    with pytest.raises(CleanupAuditRequired):
        await jobs.cleanup_daily_valid_creators_job(ctx, owner, apply=True)
    failure = json.loads(redis.values[f"daily-valid-creators:cleanup:{owner}:apply:failure"])
    assert failure == {"error_type": "CleanupAuditRequired", "phase": "apply",
                       "audit_path": str(Path("/private/cleanup-audit.json")),
                       "completed_ids": ["already-removed"]}
    assert await jobs.cleanup_daily_valid_creators_job(ctx, owner, apply=True) == {
        "status": "already_claimed"}
    assert calls == ["partial"]
