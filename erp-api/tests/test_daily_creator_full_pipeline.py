"""Full historical reconciliation remains gated, reversible and idempotent."""

import json
from copy import deepcopy
from datetime import timedelta
from pathlib import Path

import pytest

from scripts import daily_valid_creator_pipeline as pipeline
from scripts.daily_valid_creator_core import SHOP_LINES, date_millis
from scripts.daily_valid_creator_history_identity import historical_reason


@pytest.fixture
def full_pipeline(monkeypatch, tmp_path):
    day = pipeline.datetime.now(pipeline.BEIJING).date() - timedelta(days=1)
    stamp = date_millis(day)
    old_stamp = date_millis(day - timedelta(days=100))
    accounts = [
        {"accountName": account, "bdOwner": owner, "sampleApprovedDate": stamp,
         "cooperationShop": shop}
        for account, owner, shop in (
            ("active", "current-bd", "跨境3店"),
            ("inactive", "historical-correct-bd", "跨境12店"),
            ("new", "new-bd", "本土2店"),
            ("yana_ok1", "do-not-apply", "跨境3店"),
        )
    ]

    def row(record_id, account, shop, owner="wrong-bd"):
        return {"record_id": record_id, "fields": {
            "账号名称": account, "匹配店铺": shop, "BD负责人": owner,
            "同意样品日期": old_stamp, "最近有效日期": old_stamp,
            "业绩": 999, "视频数": 99, "直播数": 9,
            "保留原因": "有业绩", "数据质量备注": "old-note",
            "最新更新时间": old_stamp,
        }}

    baseline = [
        row("active-a", "active", "跨境7"),
        row("active-z", "active", "跨境7"),
        row("inactive", "inactive", "跨境4"),
        row("missing", "not-in-master", "跨境4", "keep-unproven-owner"),
        row("yana-a", " @YANA_OK1 ", "跨境7", "original-owner-a"),
        row("yana-b", "yana_ok1", "", "original-owner-b"),
    ]
    state = {
        "records": deepcopy(baseline), "baseline": baseline, "writes": [],
        "online_checks": 0, "batch_checks": 0, "target_reads": 0,
        "identity_checks": 0, "failure": None, "day": day,
        "backup_directory": tmp_path, "accounts": accounts,
    }
    cutoffs = {shop: {name: day for name in ("creators", "videos", "liveAccounts")}
               for shop in SHOP_LINES}
    state["cutoffs"] = cutoffs

    def desired_rows(base, *_):
        return {key: {
            "账号名称": source["account"], "BD负责人": source["bd"],
            "匹配店铺": "本土2店" if key[1] == "本土店" else key[1],
            "同意样品日期": date_millis(source["sample_day"]),
            "最近有效日期": stamp, "业绩": 100, "视频数": 2, "直播数": 0,
            "保留原因": "有业绩；有视频产出", "数据质量备注": "",
        } for key, source in base.items() if key[0] != "inactive"}

    async def sources(*_, **__):
        selected = [] if state["failure"] == "empty-source" else deepcopy(accounts)
        count = len(selected)
        return ({"source": "feishu-bitable-readonly", "accounts": {
            "scope": "physical_table",
            "physical_table_id": pipeline.FEISHU_MERGED_SOURCE.table_id,
            "terminal_confirmed": state["failure"] != "source",
            "unique_record_ids": state["failure"] != "duplicate-source",
            "captured_total": count,
            "final_total": count + int(state["failure"] == "missing-page"),
            "empty_placeholders": 0, "total": count, "rows": selected,
        }}, {}, {})

    async def runs(*_):
        return []

    async def identity(*_):
        state["identity_checks"] += 1

    async def target(*_):
        state["target_reads"] += 1
        result = deepcopy(state["records"])
        if state["failure"] == "race" and state["target_reads"] == 2:
            result[0]["fields"]["数据质量备注"] = "concurrent-edit"
        if state["failure"] == "protected-readback" and state["target_reads"] == 3:
            result[-2]["fields"]["BD负责人"] = "unexpected-owner"
        return result

    def online(*_):
        state["online_checks"] += 1
        if state["failure"] == "online" and state["online_checks"] == 2:
            raise ValueError("Online evidence expired before write")

    def batch(*_):
        state["batch_checks"] += 1
        if state["failure"] == "batch" and state["batch_checks"] == 2:
            raise ValueError("Batch completeness failed before write")
        return {"required_windows": 45, "reused_windows": 45}

    class FakeClient:
        async def batch_records(self, _base, _table, action, payload, *, retry_mode):
            assert retry_mode in {"idempotent", "rate_limit"}
            backups = list(tmp_path.glob("daily-creator-reconciliation-*.json"))
            assert len(backups) == 1, "Durable backup must exist before the first write"
            snapshot = json.loads(backups[0].read_text(encoding="utf-8"))
            assert snapshot["baseline"] == baseline
            state["writes"].append(action)
            if action == "batch_update":
                by_id = {record["record_id"]: record for record in state["records"]}
                for item in payload:
                    by_id[item["record_id"]]["fields"].update(item["fields"])
                return {"records": [{"record_id": item["record_id"]} for item in payload]}
            if action == "batch_create":
                created = []
                for index, item in enumerate(payload):
                    record_id = f"created-{index}"
                    state["records"].append({"record_id": record_id,
                                              "fields": deepcopy(item["fields"])})
                    created.append({"record_id": record_id})
                return {"records": created}
            if action == "batch_delete":
                historical_ids = {row["record_id"] for row in baseline}
                assert not historical_ids.intersection(payload)
                state["records"][:] = [row for row in state["records"]
                                       if row["record_id"] not in payload]
                return {"records": [{"record_id": value} for value in payload]}
            raise AssertionError("Historical records must never be deleted")

    monkeypatch.setattr(pipeline, "fetch_sources", sources)
    monkeypatch.setattr(pipeline, "validate_erp_sources", lambda *_: {
        "high": {}, "low": {}, "windows": {shop: {} for shop in SHOP_LINES}})
    monkeypatch.setattr(pipeline, "desired_rows", desired_rows)
    monkeypatch.setattr(pipeline, "load_batch_runs", runs)
    monkeypatch.setattr(pipeline, "evaluate_batch", batch)
    monkeypatch.setattr(pipeline, "validate_online_evidence", online)
    monkeypatch.setattr(pipeline, "feishu_client", FakeClient)
    monkeypatch.setattr(pipeline, "verify_target_identity", identity)
    monkeypatch.setattr(pipeline, "target_rows", target)
    monkeypatch.setattr(pipeline, "report", lambda *args: {"preview": args[4]})
    return state


async def reconcile(state, **kwargs):
    return await pipeline.reconcile(
        state["cutoffs"], state["day"], {}, refresh_history=True,
        excluded_accounts=frozenset({"yana_ok1"}),
        backup_directory=str(state["backup_directory"]), **kwargs,
    )


@pytest.mark.asyncio
async def test_full_reconciliation_corrects_history_and_preserves_protected_rows(full_pipeline):
    state = full_pipeline
    result = await reconcile(state, apply=True)
    assert result["apply"]["status"] == "verified"
    assert result["apply"]["history_reconciliation"] is True
    assert result["apply"]["second_preview"] == [0, 0, 0]
    assert result["apply"]["updated"] == 4
    assert result["apply"]["created"] == 1
    assert result["apply"]["deduplicated"] == 0
    assert result["apply"]["final_records"] == 7
    assert state["writes"] == ["batch_update", "batch_create"]
    assert (state["online_checks"], state["batch_checks"]) == (2, 2)
    assert state["identity_checks"] == 1
    assert state["target_reads"] == 3
    before = {row["record_id"]: row for row in state["baseline"]}
    after = {row["record_id"]: row for row in state["records"]}
    assert set(before) < set(after)
    for record_id in ("yana-a", "yana-b"):
        assert after[record_id] == before[record_id]
    for record_id in ("active-a", "active-z"):
        fields = after[record_id]["fields"]
        assert fields["匹配店铺"] == "跨境3"
        assert fields["BD负责人"] == "current-bd"
        assert fields["同意样品日期"] == date_millis(state["day"])
    assert historical_reason(after["active-a"]["fields"]["保留原因"])
    assert not historical_reason(after["active-z"]["fields"]["保留原因"])
    history = after["inactive"]["fields"]
    assert history["匹配店铺"] == "跨境12"
    assert history["BD负责人"] == "historical-correct-bd"
    assert history["同意样品日期"] == date_millis(state["day"])
    assert history["保留原因"].startswith("历史留存")
    assert history["业绩"] == history["视频数"] == history["直播数"] == 0
    missing = after["missing"]["fields"]
    assert missing["BD负责人"] == "keep-unproven-owner"
    assert missing["保留原因"].startswith("待核验")
    assert after["created-0"]["fields"]["匹配店铺"] == "本土2店"
    backup = json.loads(Path(result["apply"]["backup"]).read_text(encoding="utf-8"))
    assert backup["baseline"] == state["baseline"]
    assert backup["plan"]["operations"]["delete"] == []
    assert backup["plan"]["protected_record_ids"] == ["yana-a", "yana-b"]
    second = await reconcile(state)
    assert (second["preview"]["creates"], second["preview"]["updates"],
            second["preview"]["deduplicates"]) == (0, 0, 0)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure, expected", [
    ("source", "pagination evidence"),
    ("missing-page", "pagination evidence"),
    ("duplicate-source", "pagination evidence"),
    ("empty-source", "No usable Feishu creator accounts"),
    ("online", "expired before write"),
    ("batch", "completeness failed before write"),
    ("race", "Target changed after full preview"),
    ("hash", "Live preview changed"),
])
async def test_full_refresh_write_gates_leave_every_record_unchanged(
    full_pipeline, failure, expected,
):
    state = full_pipeline
    state["failure"] = failure
    options = {"expected_hash": "incorrect"} if failure == "hash" else {}
    with pytest.raises((RuntimeError, ValueError), match=expected):
        await reconcile(state, apply=True, **options)
    assert state["writes"] == []
    assert state["records"] == state["baseline"]
    assert list(state["backup_directory"].iterdir()) == []


@pytest.mark.asyncio
async def test_backup_failure_stops_full_refresh_before_write(full_pipeline, monkeypatch):
    from scripts import daily_valid_creator_snapshot

    def fail_snapshot(*_):
        raise OSError("Durable backup unavailable")

    monkeypatch.setattr(daily_valid_creator_snapshot, "save_snapshot", fail_snapshot)
    state = full_pipeline
    with pytest.raises(OSError, match="backup unavailable"):
        await reconcile(state, apply=True)
    assert state["writes"] == []
    assert state["records"] == state["baseline"]


@pytest.mark.asyncio
async def test_preview_is_readonly_and_does_not_create_backup(full_pipeline):
    state = full_pipeline
    result = await reconcile(state)
    assert result["preview"]["updates"] == 4
    assert result["preview"]["creates"] == 1
    assert result["preview"]["protected_record_ids"] == ["yana-a", "yana-b"]
    assert state["records"] == state["baseline"]
    assert state["writes"] == []
    assert list(state["backup_directory"].iterdir()) == []


@pytest.mark.asyncio
async def test_protected_readback_change_rejects_success_and_rolls_back(full_pipeline):
    state = full_pipeline
    state["failure"] = "protected-readback"
    with pytest.raises(RuntimeError, match="rollback restored target records") as caught:
        await reconcile(state, apply=True)
    assert "Protected creator records changed" in str(caught.value.__cause__)
    assert state["records"] == state["baseline"]
    assert state["writes"] == ["batch_update", "batch_create",
                               "batch_update", "batch_delete"]
    assert len(list(state["backup_directory"].glob("*.json"))) == 1
