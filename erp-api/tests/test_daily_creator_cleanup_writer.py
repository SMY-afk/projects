"""One-off deletes are frozen, backed up and never replayed after unknown results."""

import asyncio
import hashlib
import json
import os
import stat
from copy import deepcopy
from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest

from scripts import daily_valid_creator_cleanup_snapshot as snapshots
from scripts.daily_valid_creator_cleanup_plan import cleanup_preview
from scripts.daily_valid_creator_cleanup_snapshot import (
    load_cleanup_snapshot,
    save_cleanup_snapshot,
)
from scripts.daily_valid_creator_cleanup_writer import (
    CleanupAuditRequired,
    write_cleanup,
)
from scripts.daily_valid_creator_core import date_millis
from scripts.daily_valid_creator_history_identity import HISTORY_REASON
from scripts.daily_valid_creator_io import BASE, FIELD_TYPES, TABLE


def inputs(count=3):
    records, base = [], {}
    for index in range(count):
        account = f"creator{index}"
        records.append({"record_id": f"id{index}", "fields": {"账号名称": account,
            "BD负责人": "BD", "匹配店铺": "跨境3", "同意样品日期": date_millis(date(2026, 1, 1)),
            "保留原因": HISTORY_REASON, "最新更新时间": 123, "数据质量备注": "keep-original"}})
        base[(account, "跨境3")] = {"account": account, "bd": "BD",
                                "sample_day": date(2026, 1, 1), "conflict": False}
    records.append({"record_id": "protected", "fields": {"账号名称": "yana_ok1",
                   "BD负责人": "old-owner", "匹配店铺": "跨境7", "保留原因": HISTORY_REASON}})
    return records, {}, base


def snapshot(tmp_path, count=3, *, identity=None):
    records, desired, base = inputs(count)
    return save_cleanup_snapshot(tmp_path, identity=identity or {
        "app_token": BASE, "base_name": "样品--副本", "table_id": TABLE,
        "table_name": "（每日更新）有效达人"},
        schema=[{"field_id": f"field-{index}", "field_name": name, "type": kind,
                 "property": {"custom-option": ["full-property"]}}
                for index, (name, kind) in enumerate(FIELD_TYPES.items())],
        current=records, plan=cleanup_preview(records, desired, base),
        source_evidence={"scope": "physical_table", "five_shop_sources_complete": True},
        desired=desired, base=base)


class Client:
    def __init__(self, records, modes=()):
        self.records = deepcopy(records)
        self.modes = list(modes)
        self.calls = []
        self.reads = 0

    async def read(self, client):
        assert client is self
        self.reads += 1
        return deepcopy(self.records)

    async def batch_records(self, app, table, action, ids, *, retry_mode):
        assert (app, table, action, retry_mode) == (BASE, TABLE, "batch_delete", "none")
        self.calls.append(list(ids))
        mode = self.modes.pop(0) if self.modes else "success"
        if mode == "raise_before_delete":
            raise TimeoutError("do-not-print-private-detail")
        removed = ids[:1] if mode == "partial" else ids
        self.records = [row for row in self.records if row["record_id"] not in removed]
        if mode == "cancel_after_delete":
            raise asyncio.CancelledError()
        if mode in {"raise_after_delete", "partial"}:
            raise TimeoutError("do-not-print-private-detail")
        return {"records": [{"record_id": record_id, "deleted": True} for record_id in ids]}


def test_snapshot_contains_full_records_schema_properties_and_source_proof(tmp_path):
    receipt = snapshot(tmp_path)
    payload = json.loads(receipt["path"].read_text(encoding="utf-8"))
    assert payload["identity"]["table_id"] == TABLE
    assert payload["schema"][0]["property"] == {"custom-option": ["full-property"]}
    assert payload["current"] == inputs()[0]
    assert payload["source_evidence"]["five_shop_sources_complete"] is True
    assert payload["base"] and payload["plan"]["delete_ids"] == ["id0", "id1", "id2"]
    desired, base = snapshots.snapshot_projection(payload)
    assert desired == {} and base == inputs()[2]
    if os.name != "nt":
        assert stat.S_IMODE(receipt["path"].stat().st_mode) == 0o600


@pytest.mark.asyncio
async def test_success_deletes_only_frozen_ids_and_preserves_protected_fields(tmp_path):
    receipt = snapshot(tmp_path)
    client = Client(inputs()[0])
    guards = []

    async def guard():
        guards.append(len(client.calls))

    result = await write_cleanup(client, receipt, client.read, chunk_size=2, before_batch=guard)
    assert result["status"] == "verified" and result["deleted"] == 3
    assert client.calls == [["id0", "id1"], ["id2"]]
    assert guards == [0, 1]
    assert client.records == [inputs()[0][-1]]


@pytest.mark.asyncio
async def test_unknown_but_fully_applied_result_is_verified_without_replay(tmp_path):
    receipt = snapshot(tmp_path)
    client = Client(inputs()[0], ["raise_after_delete", "success"])
    result = await write_cleanup(client, receipt, client.read, chunk_size=2)
    assert result["deleted"] == 3 and result["unknown_outcomes_confirmed"] == 1
    assert client.calls == [["id0", "id1"], ["id2"]]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["partial", "raise_before_delete"])
async def test_partial_or_not_applied_unknown_outcome_stops_and_audits(tmp_path, mode):
    receipt = snapshot(tmp_path)
    client = Client(inputs()[0], [mode])
    with pytest.raises(CleanupAuditRequired) as caught:
        await write_cleanup(client, receipt, client.read, chunk_size=2)
    assert client.calls == [["id0", "id1"]]
    audit = json.loads(caught.value.audit_path.read_text(encoding="utf-8"))
    assert audit["status"] == "audit_required"
    assert "do-not-print-private-detail" not in json.dumps(audit)
    assert len(client.records) == (3 if mode == "partial" else 4)


@pytest.mark.asyncio
async def test_changed_non_target_field_blocks_delete(tmp_path):
    receipt = snapshot(tmp_path)
    client = Client(inputs()[0])
    client.records[-1]["fields"]["BD负责人"] = "manual-change"
    with pytest.raises(CleanupAuditRequired):
        await write_cleanup(client, receipt, client.read)
    assert client.calls == []


@pytest.mark.asyncio
async def test_guard_failure_happens_before_any_delete(tmp_path):
    receipt = snapshot(tmp_path)
    client = Client(inputs()[0])

    async def guard():
        raise RuntimeError("source-health-changed")

    with pytest.raises(CleanupAuditRequired):
        await write_cleanup(client, receipt, client.read, before_batch=guard)
    assert client.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("field, value", [
    ("保留原因", "current-effective"), ("BD负责人", "manual-owner"),
    ("账号名称", "yana_ok1"),
])
async def test_guard_time_target_change_blocks_delete(tmp_path, field, value):
    receipt = snapshot(tmp_path)
    client = Client(inputs()[0])

    async def guard():
        client.records[0]["fields"][field] = value

    with pytest.raises(CleanupAuditRequired):
        await write_cleanup(client, receipt, client.read, before_batch=guard)
    assert client.calls == []
    assert client.reads == 2
    assert client.records[0]["fields"][field] == value


@pytest.mark.asyncio
async def test_snapshot_tampering_is_rejected_before_any_remote_call(tmp_path):
    receipt = snapshot(tmp_path)
    payload = json.loads(receipt["path"].read_text(encoding="utf-8"))
    payload["plan"]["delete_ids"].append("protected")
    receipt["path"].write_text(json.dumps(payload), encoding="utf-8")
    client = Client(inputs()[0])
    with pytest.raises(ValueError, match="hash"):
        await write_cleanup(client, receipt, client.read)
    assert client.calls == [] and client.reads == 0


@pytest.mark.asyncio
async def test_tampered_plan_is_rejected_even_if_outer_digest_is_recomputed(tmp_path):
    receipt = snapshot(tmp_path)
    payload = json.loads(receipt["path"].read_text(encoding="utf-8"))
    payload["plan"]["delete_ids"].append("protected")
    receipt["path"].write_text(json.dumps(payload), encoding="utf-8")
    receipt["sha256"] = hashlib.sha256(receipt["path"].read_bytes()).hexdigest()
    client = Client(inputs()[0])
    with pytest.raises(ValueError, match="pure source projection"):
        await write_cleanup(client, receipt, client.read)
    assert client.calls == [] and client.reads == 0


@pytest.mark.asyncio
async def test_unstable_full_predelete_read_stops_without_a_request(tmp_path):
    receipt = snapshot(tmp_path)
    client = Client(inputs()[0])

    async def unstable_read(client):
        result = await client.read(client)
        if client.reads == 2:
            result[-1]["fields"]["BD负责人"] = "changed-between-pages"
        return result

    with pytest.raises(CleanupAuditRequired):
        await write_cleanup(client, receipt, unstable_read)
    assert client.calls == []


@pytest.mark.asyncio
async def test_cancelled_delete_is_read_back_but_never_continued(tmp_path):
    receipt = snapshot(tmp_path)
    client = Client(inputs()[0], ["cancel_after_delete"])
    with pytest.raises(CleanupAuditRequired) as caught:
        await write_cleanup(client, receipt, client.read, chunk_size=2)
    assert client.calls == [["id0", "id1"]]
    assert caught.value.completed_ids == ("id0", "id1")
    assert json.loads(caught.value.audit_path.read_text())["events"][0]["interrupted"] is True


def test_backup_creation_is_exclusive_fsynced_and_never_overwrites(tmp_path, monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 14, 12, tzinfo=UTC)

    synced = []
    original = snapshots.os.fsync

    def fsync(descriptor):
        synced.append(descriptor)
        original(descriptor)

    monkeypatch.setattr(snapshots, "datetime", Clock)
    monkeypatch.setattr(snapshots, "uuid4", lambda: SimpleNamespace(hex="exclusive-test"))
    monkeypatch.setattr(snapshots.os, "fsync", fsync)
    receipt = snapshot(tmp_path)
    original_payload = receipt["path"].read_bytes()
    assert synced
    with pytest.raises(FileExistsError):
        snapshot(tmp_path)
    assert receipt["path"].read_bytes() == original_payload
    assert load_cleanup_snapshot(receipt)["schema"][0]["property"]["custom-option"] == ["full-property"]


@pytest.mark.asyncio
async def test_guard_stops_following_batch_after_first_batch_commits(tmp_path):
    receipt = snapshot(tmp_path)
    client = Client(inputs()[0])

    async def guard():
        if client.calls:
            raise RuntimeError("source-health-changed")

    with pytest.raises(CleanupAuditRequired) as caught:
        await write_cleanup(client, receipt, client.read, chunk_size=2, before_batch=guard)
    assert client.calls == [["id0", "id1"]]
    assert caught.value.completed_ids == ("id0", "id1")


def test_backup_refuses_authentication_material_without_any_new_file(tmp_path):
    receipt = snapshot(tmp_path)
    payload = load_cleanup_snapshot(receipt)
    desired, base = snapshots.snapshot_projection(payload)
    before = set(tmp_path.iterdir())
    with pytest.raises(ValueError, match="Authentication material"):
        save_cleanup_snapshot(tmp_path, identity=payload["identity"], schema=payload["schema"],
            current=payload["current"], plan=payload["plan"], desired=desired, base=base,
            source_evidence={"headers": {"Authorization": "test-only-auth-marker"}})
    assert set(tmp_path.iterdir()) == before


def test_wrong_snapshot_identity_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="identity"):
        snapshot(tmp_path, identity={"app_token": BASE, "table_id": "wrong",
                 "base_name": "样品--副本", "table_name": "（每日更新）有效达人"})


@pytest.mark.asyncio
@pytest.mark.parametrize("chunk_size", [0, 101, True])
async def test_invalid_batch_size_is_rejected_before_api_access(tmp_path, chunk_size):
    receipt = snapshot(tmp_path)
    client = Client(inputs()[0])
    with pytest.raises(ValueError, match="batch size"):
        await write_cleanup(client, receipt, client.read, chunk_size=chunk_size)
    assert client.calls == []
