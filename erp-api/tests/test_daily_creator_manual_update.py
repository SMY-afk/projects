import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from arq.worker import create_worker, get_kwargs

from erp_api.workers import daily_valid_creator_manual_jobs as jobs
from erp_api.workers.daily_valid_creator_manual_settings import CurrentDailyCreatorWorkerSettings
from erp_api.workers.daily_valid_creator_sync_settings import DailyValidCreatorSyncWorkerSettings

OWNER = "a" * 32


def grant():
    return {"scope": jobs.SCOPE, "owner": OWNER, "excluded_accounts": ["yana_ok1", "invalid_date"],
            "expected_hash": "b" * 64, "source_backup": {
                "path": "/opt/erp/backups/daily-creator-cleanup-snapshot-proof.json", "sha256": "c" * 64}}


def redis(value):
    async def get(key):
        if key == jobs.grant_key(OWNER):
            return json.dumps(value) if value is not None else None
        return '["yana_ok1"]'
    return SimpleNamespace(get=get, set=AsyncMock(return_value=False))


@pytest.mark.asyncio
async def test_grant_protects_original_and_quality_accounts():
    value, excluded = await jobs.read_grant(redis(grant()), OWNER)
    assert value["scope"] == jobs.SCOPE
    assert excluded == frozenset({"yana_ok1", "invalid_date"})


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [("scope", "wrong"), ("owner", "wrong"),
    ("excluded_accounts", []), ("excluded_accounts", ["invalid_date"]),
    ("expected_hash", "wrong"), ("source_backup", None)])
async def test_invalid_grant_fails_before_claim(field, value):
    data = grant()
    data[field] = value
    with pytest.raises(ValueError):
        await jobs.read_grant(redis(data), OWNER)


@pytest.mark.asyncio
async def test_once_claim_prevents_replay_or_scheduled_receipt_changes():
    store = redis(grant())
    assert await jobs.update_current_daily_creators_job({"redis": store}, OWNER) == {"status": "already_claimed"}
    store.set.assert_awaited_once_with(jobs.grant_key(OWNER).removesuffix(":grant") + ":claimed", OWNER, nx=True)


def test_settings_preserve_the_real_serial_worker_configuration():
    original = get_kwargs(DailyValidCreatorSyncWorkerSettings)
    candidate = get_kwargs(CurrentDailyCreatorWorkerSettings)
    assert set(candidate) == set(original) | {"job_completion_wait"}
    assert all(candidate[key] == value for key, value in original.items() if key != "functions")
    assert candidate["functions"][:-1] == original["functions"]
    worker = create_worker(CurrentDailyCreatorWorkerSettings, handle_signals=False)
    assert worker.max_jobs == 1 and worker.queue_name == "arq:daily-valid-creators"
    assert "update_current_daily_creators_job" in worker.functions
    assert len(worker.cron_jobs) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("drift", [None, "fingerprint", "source_hash", "batch"])
async def test_current_update_success_and_source_drift(monkeypatch, drift):
    from scripts import daily_valid_creator_cleanup_pipeline as cleanup
    from scripts import daily_valid_creator_cleanup_snapshot as snapshots
    from scripts import daily_valid_creator_fresh_reconciliation as fresh
    from scripts import daily_valid_creator_io as io
    from scripts import daily_valid_creator_pipeline as pipeline

    raw = ({"complete": True}, {}, {})
    proof = {"fingerprint": "snapshot", "batch_date": "2026-10-13", "cutoffs": {},
             "source_content_hash": cleanup.content_hash(raw)}
    data = {"source_evidence": proof, "current": [{"record_id": "frozen"}]}
    if drift == "source_hash":
        proof["source_content_hash"] = "bad"
    snapshot = ({}, {}, "changed" if drift == "fingerprint" else "snapshot",
                "2026-10-12" if drift == "batch" else "2026-10-13", {})
    monkeypatch.setattr(snapshots, "load_cleanup_snapshot", lambda *_: data)
    monkeypatch.setattr(snapshots, "snapshot_projection", lambda *_: ({}, {}))
    monkeypatch.setattr(fresh, "fresh_reconciliation_preview", lambda *_a, **_kw: {"hash": "b" * 64})
    monkeypatch.setattr(cleanup, "require_cleanup_sources", AsyncMock(return_value=snapshot))
    monkeypatch.setattr(io, "fetch_sources", AsyncMock(return_value=raw))
    apply = AsyncMock(return_value={"apply": {"status": "verified", "second_preview": [0, 0, 0]}})
    monkeypatch.setattr(pipeline, "reconcile", apply)
    store = redis(grant())
    store.set = AsyncMock(return_value=True)
    if drift:
        with pytest.raises(RuntimeError):
            await jobs.update_current_daily_creators_job({"redis": store}, OWNER)
        apply.assert_not_awaited()
    else:
        result = await jobs.update_current_daily_creators_job({"redis": store}, OWNER)
        assert result["second_preview"] == [0, 0, 0]
        assert apply.await_args.kwargs["expected_source_hash"] == proof["source_content_hash"]
        assert apply.await_args.kwargs["expected_target_hash"] == cleanup.content_hash(data["current"])
        assert apply.await_args.kwargs["excluded_accounts"] == frozenset({"yana_ok1", "invalid_date"})
    assert all("manual-update:" in call.args[0] for call in store.set.await_args_list)
