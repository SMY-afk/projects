"""One-off cleanup never weakens the regular creator-sync gates."""

import asyncio
from copy import deepcopy
from datetime import UTC, date, datetime

import pytest

from scripts import daily_valid_creator_cleanup_pipeline as cleanup
from scripts.daily_valid_creator_accounts import select_accounts
from scripts.daily_valid_creator_cleanup_plan import cleanup_preview
from scripts.daily_valid_creator_cleanup_snapshot import save_cleanup_snapshot
from scripts.daily_valid_creator_cleanup_writer import (
    CleanupAuditRequired,
    write_cleanup,
)
from scripts.daily_valid_creator_history_identity import HISTORY_REASON


@pytest.fixture
def setup_cleanup(monkeypatch, tmp_path):
    state = {"calls": [], "failure": None, "reads": 0, "schema_reads": 0,
             "source_reads": 0, "guard_calls": 0,
             "excluded": frozenset({"yana_ok1"})}
    current = [{"record_id": "inactive", "fields": {"账号名称": "inactive"}}]
    plan = {"hash": "a" * 64, "delete_ids": ["inactive"],
            "counts": {"delete": 1}, "protected_record_ids": ["yana"]}
    source = {"accounts": {"rows": []}, "high": {}, "low": {}, "windows": {}}
    snapshot = ({}, {"source": "direct_tk_sources"}, "fingerprint", date(2026, 10, 13), {})

    async def guard(*_, **__):
        state["guard_calls"] += 1
        state["calls"].append("guard")
        if state["failure"] == "gate":
            raise RuntimeError("source_not_ready")
        if state["failure"] == "batch-gate" and state["guard_calls"] == 3:
            raise RuntimeError("batch incomplete")
        if state["failure"] == "post-gate" and state["guard_calls"] == 4:
            raise RuntimeError("post health failure")
        if state["failure"] == "post-cancel" and state["guard_calls"] == 4:
            raise asyncio.CancelledError()
        return snapshot

    async def fetch(*_, **__):
        state["source_reads"] += 1
        state["calls"].append("sources")
        data = {"master": "complete"}
        if state["failure"] == "sources" and state["source_reads"] == 2:
            data["master"] = "changed"
        return data, {}, {}

    async def identity(*_):
        state["calls"].append("identity")

    async def schema(*_):
        state["schema_reads"] += 1
        data = [{"field_id": "account", "field_name": "账号名称", "property": {}}]
        if state["failure"] == "schema" and state["schema_reads"] == 2:
            data[0]["property"] = {"changed": True}
        return data

    async def rows(*_):
        state["reads"] += 1
        data = deepcopy(current)
        if state["failure"] == "target" and state["reads"] == 2:
            data[0]["fields"]["账号名称"] = "concurrent-change"
        if "delete" in state["calls"]:
            return []
        return data

    def backup(*_, **kwargs):
        state["calls"].append("backup")
        assert kwargs["current"] == current
        assert kwargs["schema"][0]["property"] == {}
        assert kwargs["desired"] == {}
        assert kwargs["base"] == {}
        assert kwargs["excluded_accounts"] == state["excluded"]
        if state["failure"] == "backup":
            raise OSError("durable backup failed")
        return {"path": str(tmp_path / "snapshot.json"), "sha256": "b" * 64, "records": 1}

    async def writer(_client, receipt, reread, *, excluded_accounts, before_batch):
        assert receipt["records"] == 1
        assert excluded_accounts == state["excluded"]
        assert callable(reread)
        await before_batch()
        state["calls"].append("delete")
        return {"status": "verified", "deleted": 1, "final_records": 0}

    monkeypatch.setattr(cleanup, "require_cleanup_sources", guard)
    monkeypatch.setattr(cleanup, "fetch_sources", fetch)
    monkeypatch.setattr(cleanup, "validate_sources", lambda *_: source)
    monkeypatch.setattr(cleanup, "select_accounts", lambda *_: ({}, 0))
    monkeypatch.setattr(cleanup, "desired_shop_rows", lambda *_: {})
    monkeypatch.setattr(cleanup, "cleanup_preview", lambda records, *_args, **_kw:
                        deepcopy(plan) if records else {**plan, "delete_ids": []})
    monkeypatch.setattr(cleanup, "feishu_client", object)
    monkeypatch.setattr(cleanup, "verify_target_identity", identity)
    monkeypatch.setattr(cleanup, "read_target_schema", schema)
    monkeypatch.setattr(cleanup, "target_rows", rows)
    monkeypatch.setattr(cleanup, "save_cleanup_snapshot", backup)
    monkeypatch.setattr(cleanup, "write_cleanup", writer)
    monkeypatch.setattr(cleanup, "_now", lambda _: datetime(2026, 10, 14, 6, tzinfo=UTC))
    return state, tmp_path


async def run_cleanup(setup, **kwargs):
    _, directory = setup
    return await cleanup.cleanup({}, backup_directory=str(directory), **kwargs)


@pytest.mark.asyncio
async def test_preview_is_backed_up_and_does_not_delete(setup_cleanup):
    state, _ = setup_cleanup
    result = await run_cleanup(setup_cleanup)
    assert result["preview"]["hash"] == "a" * 64
    assert result["backup"]["records"] == 1
    assert state["source_reads"] == 2
    assert "delete" not in state["calls"]


@pytest.mark.asyncio
async def test_apply_revalidates_after_backup_and_before_exact_delete(setup_cleanup):
    state, _ = setup_cleanup
    result = await run_cleanup(setup_cleanup, apply=True, expected_hash="a" * 64)
    assert result["apply"]["status"] == "verified"
    assert state["calls"].index("backup") < state["calls"].index("delete")
    assert state["calls"].count("sources") == 2
    assert state["guard_calls"] >= 3


@pytest.mark.asyncio
@pytest.mark.parametrize("failure, message", [
    ("gate", "source_not_ready"), ("backup", "durable backup failed"),
    ("sources", "Source content changed"), ("schema", "Target schema changed"),
    ("target", "Target records changed"), ("batch-gate", "batch incomplete"),
])
async def test_cleanup_fail_closed_without_any_delete(setup_cleanup, failure, message):
    state, _ = setup_cleanup
    state["failure"] = failure
    with pytest.raises((RuntimeError, OSError), match=message):
        await run_cleanup(setup_cleanup, apply=True, expected_hash="a" * 64)
    assert "delete" not in state["calls"]
    if failure == "gate":
        assert state["calls"] == ["guard"]


@pytest.mark.asyncio
async def test_wrong_hash_never_backs_up_or_deletes(setup_cleanup):
    state, _ = setup_cleanup
    with pytest.raises(RuntimeError, match="Authorized preview hash"):
        await run_cleanup(setup_cleanup, apply=True, expected_hash="c" * 64)
    assert "backup" not in state["calls"]
    assert "delete" not in state["calls"]


@pytest.mark.asyncio
async def test_yana_exclusion_is_mandatory_before_any_read(setup_cleanup):
    state, _ = setup_cleanup
    with pytest.raises(ValueError, match="yana_ok1"):
        await run_cleanup(setup_cleanup, excluded_accounts=frozenset())
    assert state["calls"] == []


@pytest.mark.asyncio
async def test_all_granted_protected_accounts_reach_backup_and_writer(setup_cleanup):
    state, _ = setup_cleanup
    state["excluded"] = frozenset({"yana_ok1", "another_protected"})
    result = await run_cleanup(setup_cleanup, apply=True, expected_hash="a" * 64,
                              excluded_accounts=state["excluded"])
    assert result["apply"]["status"] == "verified"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["post-gate", "post-cancel"])
async def test_post_delete_gate_failure_retains_completed_ids_and_audit(setup_cleanup, failure):
    state, directory = setup_cleanup
    state["failure"] = failure
    with pytest.raises(CleanupAuditRequired) as caught:
        await run_cleanup(setup_cleanup, apply=True, expected_hash="a" * 64)
    assert caught.value.completed_ids == ("inactive",)
    assert caught.value.audit_path.exists()
    assert len(list(directory.glob("daily-creator-cleanup-post-verification-*.json"))) == 1
    assert state["calls"].count("delete") == 1


@pytest.mark.asyncio
async def test_real_snapshot_writer_and_plan_integrate_without_touching_yana(
    setup_cleanup, monkeypatch,
):
    state, directory = setup_cleanup
    baseline = [
        {"record_id": "inactive", "fields": {"账号名称": "inactive", "匹配店铺": "跨境3",
            "BD负责人": "BD", "保留原因": HISTORY_REASON, "同意样品日期": "2026-01-01"}},
        {"record_id": "yana", "fields": {"账号名称": "yana_ok1", "匹配店铺": "跨境7",
            "BD负责人": "preserved-owner", "保留原因": HISTORY_REASON}},
    ]
    base = {("inactive", "跨境3"): {"account": "inactive", "bd": "BD",
                                    "sample_day": date(2026, 1, 1), "conflict": False}}

    class Client:
        def __init__(self):
            self.records = deepcopy(baseline)
            self.calls = []

        async def batch_records(self, _base, _table, action, ids, *, retry_mode):
            assert action == "batch_delete" and retry_mode == "none"
            assert ids == ["inactive"]
            self.calls.append(ids)
            self.records = [row for row in self.records if row["record_id"] not in ids]
            return {"records": [{"record_id": value, "deleted": True} for value in ids]}

    client = Client()

    async def rows(*_):
        return deepcopy(client.records)

    async def schema(*_):
        return [{"field_id": f"field-{index}", "field_name": name, "type": kind,
                 "property": {"custom": "full-properties"}}
                for index, (name, kind) in enumerate(cleanup.FIELD_TYPES.items())]

    monkeypatch.setattr(cleanup, "select_accounts", lambda *_: (base, 0))
    monkeypatch.setattr(cleanup, "cleanup_preview", cleanup_preview)
    monkeypatch.setattr(cleanup, "save_cleanup_snapshot", save_cleanup_snapshot)
    monkeypatch.setattr(cleanup, "write_cleanup", write_cleanup)
    monkeypatch.setattr(cleanup, "target_rows", rows)
    monkeypatch.setattr(cleanup, "read_target_schema", schema)
    monkeypatch.setattr(cleanup, "feishu_client", lambda: client)
    expected = cleanup_preview(baseline, {}, base)
    result = await run_cleanup(setup_cleanup, apply=True, expected_hash=expected["hash"])
    assert result["apply"]["deleted"] == 1
    assert result["apply"]["final_records"] == 1
    assert result["apply"]["second_preview_delete"] == 0
    assert client.records == [baseline[-1]]
    assert len(list(directory.glob("daily-creator-cleanup-snapshot-*.json"))) == 1
    assert len(list(directory.glob("daily-creator-cleanup-audit-*.json"))) == 1
    assert state["source_reads"] == 2


def test_real_master_projection_preserves_integer_conflict_contract(monkeypatch):
    rows = [
        {"accountName": "inactive", "bdOwner": "BD", "sampleApprovedDate": "2026-01-01",
         "cooperationShop": "跨境3店"},
        {"accountName": "inactive", "bdOwner": "different", "sampleApprovedDate": "2025-01-01",
         "cooperationShop": "跨境3店"},
    ]
    monkeypatch.setattr(cleanup, "validate_sources", lambda *_: {
        "accounts": {"rows": rows}, "high": {}, "low": {}, "windows": {}})
    monkeypatch.setattr(cleanup, "select_accounts", select_accounts)
    monkeypatch.setattr(cleanup, "desired_shop_rows", lambda *_: {})
    window = cleanup.sample_window_for_day(date(2026, 10, 14))
    _, base, desired, conflicts = cleanup._projection(({}, {}, {}), {}, window)
    assert isinstance(conflicts, int)
    assert conflicts == 1
    assert base[("inactive", "跨境3")]["bd"] == "BD"
    assert desired == {}
