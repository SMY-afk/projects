import sys
from copy import deepcopy
from datetime import UTC, date, datetime, timedelta

import pytest

from scripts import daily_valid_creator_pipeline as pipeline
from scripts import daily_valid_creator_sync as sync
from scripts.daily_valid_creator_core import (
    SHOP_ZONE,
    account_key,
    date_millis,
    date_value,
    desired_rows,
    select_base_accounts,
    validate_sources,
)
from scripts.daily_valid_creator_dates import parse_shop_cutoffs
from scripts.daily_valid_creator_online import validate_online_evidence
from scripts.daily_valid_creator_sample import sample_date, sample_window_for_day
from scripts.daily_valid_creator_sync import main, preview
from scripts.daily_valid_creator_writer import write_operations
from scripts.daily_valid_creator_shop_rows import shop_record_key


def test_business_key_and_latest_nonempty_bd() -> None:
    tables = [
        {
            "productLine": "童车",
            "total": 3,
            "rows": [
                {
                    "accountName": " @ABC\u200b ",
                    "bdOwner": "旧BD",
                    "sampleApprovedDate": "2026-09-01",
                },
                {
                    "accountName": "abc",
                    "bdOwner": "新BD",
                    "sampleApprovedDate": "2026-10-01",
                },
                {
                    "accountName": "ABC",
                    "bdOwner": "",
                    "sampleApprovedDate": "2026-10-03",
                },
            ],
        },
        {
            "productLine": "遥控车",
            "total": 1,
            "rows": [
                {
                    "accountName": "abc",
                    "bdOwner": "遥控BD",
                    "sampleApprovedDate": "2026-09-02",
                },
            ],
        },
    ]
    selected, conflicts = select_base_accounts(
        tables, (date(2026, 8, 6), date(2026, 10, 6))
    )
    assert account_key(" @ABC\u200b ") == "abc"
    assert conflicts == 1
    assert selected[("童车", "abc")]["bd"] == "新BD"
    assert selected[("童车", "abc")]["sample_day"] == date(2026, 10, 3)
    assert selected[("遥控车", "abc")]["bd"] == "遥控BD"


def test_erp_event_date_uses_shop_timezone() -> None:
    assert date_value("2026-10-02T02:00:00Z", SHOP_ZONE) == date(2026, 10, 1)


def test_sample_date_uses_current_window_for_yearless_values() -> None:
    window = (date(2026, 8, 6), date(2026, 10, 6))
    assert sample_date("1791043200000", window) == date(2026, 10, 4)
    assert sample_date("2026.10.04", window) == date(2026, 10, 4)
    assert sample_date("10.4", window) == date(2026, 10, 4)
    assert sample_date("4.16", window) is None
    assert sample_date("2026-04-16", window) == date(2026, 4, 16)


def test_sample_window_matches_erp_skill_inclusive_60_days() -> None:
    window = sample_window_for_day(date(2026, 10, 6))
    assert window == (date(2026, 8, 8), date(2026, 10, 6))
    assert sample_date("8.7", window) is None
    assert sample_date("8.8", window) == date(2026, 8, 8)


def test_recent_sample_approval_alone_keeps_creator() -> None:
    base = {
        ("遥控车", "dadboughtit"): {
            "account": "dadboughtit",
            "bd": "帝维",
            "sample_day": date(2026, 10, 4),
            "conflict": False,
        }
    }
    empty_shop = {"creators": [], "videos": [], "liveAccounts": []}
    shops = ("跨境3", "跨境7", "跨境4", "跨境12", "本土店")
    windows = {
        name: {
            "creators": (date(2026, 8, 4), date(2026, 10, 4)),
            "videos": (date(2026, 8, 3), date(2026, 10, 3)),
            "liveAccounts": (date(2026, 8, 4), date(2026, 10, 4)),
        }
        for name in shops
    }
    desired = desired_rows(
        base,
        {name: empty_shop for name in shops},
        {name: empty_shop for name in shops},
        windows,
        sample_window=(date(2026, 8, 6), date(2026, 10, 6)),
    )
    row = desired[("遥控车", "dadboughtit")]
    assert row["BD负责人"] == "帝维"
    assert row["最近有效日期"] == date_millis(date(2026, 10, 4))
    assert row["保留原因"] == "有寄样"
    assert (row["业绩"], row["视频数"], row["直播数"]) == (0, 0, 0)
    assert row["匹配店铺"] == ""


def test_apply_requires_fresh_matching_direct_tk_dates() -> None:
    now = datetime(2026, 10, 5, 1, 30, tzinfo=UTC)
    evidence = {
        "source": "direct_tk_sources",
        "shops": [
            {
                "shop": name,
                "observed_at": now.isoformat(),
                "creators": "2026-10-03",
                "videos": "2026-10-01",
                "liveAccounts": "2026-10-02",
            }
            for name in ("跨境3", "跨境7", "跨境4", "跨境12", "本土店")
        ],
    }
    cutoffs = parse_shop_cutoffs(
        [
            f"{name},2026-10-03,2026-10-01,2026-10-02"
            for name in ("跨境3", "跨境7", "跨境4", "跨境12", "本土店")
        ]
    )
    validate_online_evidence(evidence, cutoffs, now)
    reusable = deepcopy(evidence)
    reusable["shops"][0]["observed_at"] = (now - timedelta(hours=2)).isoformat()
    validate_online_evidence(reusable, cutoffs, now)
    with pytest.raises(ValueError, match="missing shop"):
        validate_online_evidence(
            {**evidence, "shops": evidence["shops"][:-1]},
            cutoffs,
            now,
        )
    stale = deepcopy(evidence)
    stale["shops"][0]["observed_at"] = (
        now - timedelta(hours=6, minutes=1)
    ).isoformat()
    with pytest.raises(ValueError, match="stale"):
        validate_online_evidence(stale, cutoffs, now)
    mismatch = deepcopy(evidence)
    mismatch["shops"][0]["videos"] = "2026-10-03"
    with pytest.raises(ValueError, match="cutoff mismatch"):
        validate_online_evidence(mismatch, cutoffs, now)


@pytest.mark.asyncio
async def test_apply_without_online_evidence_stops_before_source_read(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "daily_valid_creator_sync",
            *[
                value
                for name in ("跨境3", "跨境7", "跨境4", "跨境12", "本土店")
                for value in (
                    "--shop-cutoff",
                    f"{name},2026-10-03,2026-10-01,2026-10-02",
                )
            ],
            "--apply-hash",
            "test",
        ],
    )
    with pytest.raises(ValueError, match="direct TK online evidence is required"):
        await main()


@pytest.mark.asyncio
async def test_failed_batch_gate_stops_before_any_feishu_read(monkeypatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "daily_valid_creator_sync",
            *[
                value
                for name in ("跨境3", "跨境7", "跨境4", "跨境12", "本土店")
                for value in (
                    "--shop-cutoff",
                    f"{name},2026-10-03,2026-10-01,2026-10-02",
                )
            ],
            "--online-evidence-json",
            "verified.json",
        ],
    )
    monkeypatch.setattr(sync, "load_online_evidence", lambda *_: None)

    async def no_runs(*_):
        return []

    async def forbidden_source_read(*_):
        raise AssertionError("Source read must not start after failed batch gate")

    monkeypatch.setattr(pipeline, "validate_online_evidence", lambda *_: None)
    monkeypatch.setattr(pipeline, "load_batch_runs", no_runs)
    monkeypatch.setattr(pipeline, "fetch_sources", forbidden_source_read)
    with pytest.raises(ValueError, match="Batch gate failed"):
        await main()


def test_preview_counts_update_create_deduplicate_and_retain() -> None:
    desired = {
        ("童车", "abc", ""): {"产品线": "童车", "账号名称": "@ABC", "BD负责人": "新BD"},
        ("遥控车", "new", ""): {"产品线": "遥控车", "账号名称": "new", "BD负责人": "BD"},
    }
    current = [
        {
            "record_id": "old",
            "fields": {
                "产品线": "童车",
                "账号名称": "abc",
                "BD负责人": "旧BD",
                "同意样品日期": "2026-08-01",
            },
        },
        {
            "record_id": "newer",
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
    plan = preview({shop_record_key(fields): fields for fields in desired.values()}, current)
    assert (
        plan["updates"],
        plan["creates"],
        plan["deduplicates"],
        plan["retained"],
    ) == (1, 1, 0, 2)
    assert plan["operations"]["delete"] == []
    assert plan["retained_unscoped_duplicates"] == 1


def test_source_window_and_preview_keep_target_only_record() -> None:
    creator_end = date(2026, 10, 3)
    video_end = date(2026, 10, 1)
    tables = [
        {
            "productLine": line,
            "total": 1,
            "rows": [
                {
                    "accountName": "@abc",
                    "bdOwner": "BD",
                    "sampleApprovedDate": "2026-09-01",
                },
            ],
        }
        for line in ("童车", "遥控车")
    ]
    shops = {}
    for name, line in (
        ("跨境3", "童车"),
        ("跨境7", "童车"),
        ("跨境4", "遥控车"),
        ("跨境12", "遥控车"),
        ("本土店", "遥控车"),
    ):
        shops[name] = {
            "shopName": name,
            "productLine": line,
            "sourceWindows": {
                "creators": {"from": "2026-08-03", "to": "2026-10-03"},
                "videos": {"from": "2026-08-01", "to": "2026-10-01"},
                "liveAccounts": {"from": "2026-08-03", "to": "2026-10-03"},
            },
            "totals": {"creators": 0, "videos": 0, "liveAccounts": 0},
            "creators": [],
            "videos": [],
            "liveAccounts": [],
        }
    shops["跨境3"]["totals"]["creators"] = 1
    shops["跨境3"]["creators"] = [{"username": "abc", "affiliateGmvMinor": 12345}]
    shops["本土店"]["totals"]["videos"] = 1
    shops["本土店"]["videos"] = [
        {"creatorUsername": "abc", "videoPostTime": "2026-10-02T02:00:00Z"},
    ]
    high = {"source": "local-erp-affiliate-center", "shops": list(shops.values())}
    low = {"source": "local-erp-affiliate-center", "shops": list(shops.values())}
    feishu = {"source": "feishu-bitable-readonly", "tables": tables}
    cutoffs = {
        name: {
            "creators": creator_end,
            "videos": video_end,
            "liveAccounts": creator_end,
        }
        for name in shops
    }
    source = validate_sources(feishu, high, low, cutoffs)
    base, _ = select_base_accounts(
        tables, (date(2026, 8, 6), date(2026, 10, 6))
    )
    desired = desired_rows(
        base,
        source["high"],
        source["low"],
        source["windows"],
        (date(2026, 8, 6), date(2026, 10, 6)),
    )
    assert len(desired) == 2
    assert desired[("童车", "abc")]["业绩"] == 123.45
    assert desired[("童车", "abc")]["保留原因"] == "有业绩；有寄样"
    assert desired[("遥控车", "abc")]["视频数"] == 1
    assert desired[("遥控车", "abc")]["匹配店铺"] == "本土2店"
    current = [{"record_id": "old", "fields": {"产品线": "童车", "账号名称": "other"}}]
    plan = preview({shop_record_key(fields): fields for fields in desired.values()}, current)
    assert (
        plan["updates"],
        plan["creates"],
        plan["retained"],
        plan["deduplicates"],
    ) == (0, 2, 1, 0)


@pytest.mark.asyncio
async def test_writer_rolls_back_after_readback_failure() -> None:
    baseline = [
        {
            "record_id": "old",
            "fields": {
                "产品线": "童车",
                "账号名称": "abc",
                "BD负责人": "旧BD",
                "最新更新时间": 123,
            },
        }
    ]
    records = deepcopy(baseline)

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
                for index, item in enumerate(payload):
                    records.append(
                        {"record_id": f"new-{index}", "fields": item["fields"]}
                    )
                return {
                    "records": [
                        {"record_id": f"new-{index}"} for index in range(len(payload))
                    ]
                }
            if action == "batch_delete":
                records[:] = [row for row in records if row["record_id"] not in payload]
                return {"records": [{"record_id": record_id} for record_id in payload]}
            raise AssertionError(action)

    async def reread(_client):
        return deepcopy(records)

    async def failed_verify():
        raise RuntimeError("verification mismatch")

    operations = {
        "update": [("old", {"BD负责人": "新BD"})],
        "create": [{"产品线": "遥控车", "账号名称": "new", "BD负责人": "BD"}],
        "delete": [],
    }
    with pytest.raises(RuntimeError, match="rollback restored"):
        await write_operations(
            FakeClient(), operations, baseline, 456, reread, failed_verify
        )
    assert len(records) == 1
    assert records[0]["fields"]["BD负责人"] == "旧BD"
    assert records[0]["fields"]["最新更新时间"] == 123


@pytest.mark.asyncio
async def test_writer_reports_changed_ids_when_deleted_duplicate_is_restored() -> None:
    baseline = [
        {
            "record_id": "keeper",
            "fields": {"产品线": "童车", "账号名称": "abc", "BD负责人": "BD"},
        },
        {
            "record_id": "duplicate",
            "fields": {"产品线": "童车", "账号名称": "abc", "BD负责人": "旧BD"},
        },
    ]
    records = deepcopy(baseline)

    class FakeClient:
        async def batch_records(self, _base, _table, action, payload, *, retry_mode):
            del retry_mode
            if action == "batch_delete":
                records[:] = [row for row in records if row["record_id"] not in payload]
                return {"records": [{"record_id": value} for value in payload]}
            if action == "batch_create":
                records.append(
                    {"record_id": "restored-new-id", "fields": payload[0]["fields"]}
                )
                return {"records": [{"record_id": "restored-new-id"}]}
            raise AssertionError(action)

    async def reread(_client):
        return deepcopy(records)

    async def failed_verify():
        raise RuntimeError("verification mismatch")

    with pytest.raises(RuntimeError, match="record IDs changed"):
        await write_operations(
            FakeClient(),
            {"update": [], "create": [], "delete": ["duplicate"]},
            baseline,
            123,
            reread,
            failed_verify,
        )
    assert {row["fields"]["BD负责人"] for row in records} == {"BD", "旧BD"}
