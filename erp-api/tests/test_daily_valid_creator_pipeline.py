from copy import deepcopy
from datetime import date

import pytest

from scripts import daily_valid_creator_pipeline as pipeline
from scripts.daily_valid_creator_core import SHOP_LINES


@pytest.mark.asyncio
async def test_apply_rereads_fields_keys_and_zero_difference(monkeypatch) -> None:
    cutoffs = {
        name: {
            "creators": date(2026, 10, 3),
            "videos": date(2026, 10, 1),
            "liveAccounts": date(2026, 10, 2),
        }
        for name in SHOP_LINES
    }
    desired = {
        ("abc", ""): {
            "账号名称": "abc",
            "BD负责人": "新BD",
            "同意样品日期": "2026-09-01",
        },
        ("new", ""): {"账号名称": "new", "BD负责人": "BD"},
    }
    records = [
        {
            "record_id": "older",
            "fields": {
                "产品线": "童车",
                "账号名称": "abc",
                "BD负责人": "旧BD",
                "同意样品日期": "2026-08-01",
            },
        },
        {
            "record_id": "keeper",
            "fields": {
                "产品线": "童车",
                "账号名称": "abc",
                "BD负责人": "旧BD",
                "同意样品日期": "2026-09-01",
            },
        },
        {
            "record_id": "retained",
            "fields": {"产品线": "童车", "账号名称": "other", "BD负责人": "BD"},
        },
    ]

    class FakeClient:
        async def batch_records(self, _base, _table, action, payload, *, retry_mode):
            del retry_mode
            if action == "batch_update":
                for item in payload:
                    row = next(
                        row for row in records if row["record_id"] == item["record_id"]
                    )
                    row["fields"].update(item["fields"])
                return {
                    "records": [{"record_id": item["record_id"]} for item in payload]
                }
            if action == "batch_create":
                for item in payload:
                    records.append({"record_id": "created", "fields": item["fields"]})
                return {"records": [{"record_id": "created"}]}
            if action == "batch_delete":
                records[:] = [row for row in records if row["record_id"] not in payload]
                return {"records": [{"record_id": value} for value in payload]}
            raise AssertionError(action)

    async def fake_runs(*_):
        return []

    async def fake_sources(*_, **__):
        return ({}, {}, {})

    async def fake_target(*_):
        return deepcopy(records)

    async def fake_identity(*_):
        return None

    monkeypatch.setattr(pipeline, "validate_online_evidence", lambda *_: None)
    monkeypatch.setattr(pipeline, "load_batch_runs", fake_runs)
    monkeypatch.setattr(pipeline, "evaluate_batch", lambda *_: {"required_windows": 45})
    monkeypatch.setattr(pipeline, "fetch_sources", fake_sources)
    monkeypatch.setattr(
        pipeline,
        "validate_sources",
        lambda *_: {
            "accounts": {"rows": [], "total": 0, "scope": "physical_table"},
            "high": {},
            "low": {},
            "windows": {name: {} for name in SHOP_LINES},
        },
    )
    monkeypatch.setattr(pipeline, "select_base_accounts", lambda *_: ({}, 0))
    monkeypatch.setattr(pipeline, "desired_rows", lambda *_: desired)
    monkeypatch.setattr(pipeline, "feishu_client", FakeClient)
    monkeypatch.setattr(pipeline, "verify_target_identity", fake_identity)
    monkeypatch.setattr(pipeline, "target_rows", fake_target)
    monkeypatch.setattr(pipeline, "report", lambda *args: {"preview": args[4]})
    result = await pipeline.reconcile(cutoffs, date(2026, 10, 5), {}, apply=True)
    assert result["apply"]["second_preview"] == [0, 0, 0]
    assert (
        result["apply"]["updated"],
        result["apply"]["created"],
        result["apply"]["deduplicated"],
        result["apply"]["retained"],
    ) == (1, 1, 0, 2)
    assert len(records) == 4
    assert {row["record_id"] for row in records} == {"older", "keeper", "retained", "created"}


@pytest.mark.asyncio
async def test_bad_preview_hash_makes_no_feishu_write(monkeypatch) -> None:
    cutoffs = {
        name: {
            "creators": date(2026, 10, 3),
            "videos": date(2026, 10, 1),
            "liveAccounts": date(2026, 10, 2),
        }
        for name in SHOP_LINES
    }

    async def fake_runs(*_):
        return []

    async def fake_sources(*_, **__):
        return ({}, {}, {})

    async def fake_target(*_):
        return []

    async def fake_identity(*_):
        return None

    monkeypatch.setattr(pipeline, "validate_online_evidence", lambda *_: None)
    monkeypatch.setattr(pipeline, "load_batch_runs", fake_runs)
    monkeypatch.setattr(pipeline, "evaluate_batch", lambda *_: {})
    monkeypatch.setattr(pipeline, "fetch_sources", fake_sources)
    monkeypatch.setattr(
        pipeline,
        "validate_sources",
        lambda *_: {
            "accounts": {"rows": []},
            "high": {},
            "low": {},
            "windows": {name: {} for name in SHOP_LINES},
        },
    )
    monkeypatch.setattr(pipeline, "select_base_accounts", lambda *_: ({}, 0))
    monkeypatch.setattr(pipeline, "desired_rows", lambda *_: {})
    monkeypatch.setattr(pipeline, "feishu_client", lambda: object())
    monkeypatch.setattr(pipeline, "verify_target_identity", fake_identity)
    monkeypatch.setattr(pipeline, "target_rows", fake_target)
    monkeypatch.setattr(pipeline, "report", lambda *args: {})

    async def forbidden_write(*_):
        raise AssertionError("No write expected")

    monkeypatch.setattr(pipeline, "write_operations", forbidden_write)
    with pytest.raises(RuntimeError, match="preview changed"):
        await pipeline.reconcile(
            cutoffs, date(2026, 10, 5), {}, apply=True, expected_hash="wrong"
        )
