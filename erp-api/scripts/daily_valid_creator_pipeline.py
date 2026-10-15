"""Validated preview, Feishu apply, and exact reread reconciliation."""

from __future__ import annotations

from datetime import UTC, date, datetime

from erp_api.services.daily_valid_creator_schedule import (
    validate_daily_valid_creator_source_batch,
)
from erp_api.services.feishu_creator_export_service import FEISHU_MERGED_SOURCE
from scripts.daily_valid_creator_accounts import select_accounts
from scripts.daily_valid_creator_batch import evaluate_batch, load_batch_runs
from scripts.daily_valid_creator_core import (
    BEIJING,
    date_millis,
    date_value,
    validate_erp_sources,
)
from scripts.daily_valid_creator_dates import ShopCutoffs
from scripts.daily_valid_creator_io import (
    EXPORT_URL,
    feishu_client,
    fetch_sources,
    target_rows,
    verify_target_identity,
)
from scripts.daily_valid_creator_online import validate_online_evidence
from scripts.daily_valid_creator_sample import sample_window_for_day
from scripts.daily_valid_creator_shop_rows import desired_shop_rows as desired_rows
from scripts.daily_valid_creator_sync import equal_field, preview, report, target_key
from scripts.daily_valid_creator_writer import write_operations


async def reconcile(
    cutoffs: ShopCutoffs,
    batch_date: date,
    online_evidence: dict,
    *,
    apply: bool = False,
    expected_hash: str | None = None,
    export_url: str = EXPORT_URL,
    refresh_history: bool = False,
    excluded_accounts: frozenset[str] = frozenset(),
    backup_directory: str | None = None,
    scheduled_update: bool = False,
    expected_source_hash: str | None = None,
    expected_target_hash: str | None = None,
) -> dict:
    if scheduled_update:
        validate_daily_valid_creator_source_batch(batch_date, datetime.now(UTC))
    validate_online_evidence(online_evidence, cutoffs)
    today = datetime.now(BEIJING).date()
    sample_window = sample_window_for_day(today)
    batch = evaluate_batch(
        cutoffs, batch_date, await load_batch_runs(cutoffs, batch_date)
    )
    feishu, high, low = await fetch_sources(cutoffs, export_url=export_url)
    if expected_source_hash is not None:
        from scripts.daily_valid_creator_cleanup_pipeline import content_hash
        if content_hash((feishu, high, low)) != expected_source_hash:
            raise RuntimeError("Frozen source content changed before current-table update")
    source = validate_sources(feishu, high, low, cutoffs)
    base, conflicts = select_base_accounts(source["accounts"]["rows"], sample_window)
    desired = desired_rows(
        base, source["high"], source["low"], source["windows"], sample_window
    )
    client = feishu_client()
    await verify_target_identity(client)
    current = await target_rows(client)
    if expected_target_hash is not None:
        from scripts.daily_valid_creator_cleanup_pipeline import content_hash
        if content_hash(current) != expected_target_hash:
            raise RuntimeError("Frozen target content changed before current-table update")
    def make_plan(records):
        if refresh_history:
            from scripts.daily_valid_creator_fresh_reconciliation import (
                fresh_reconciliation_preview,
            )

            return fresh_reconciliation_preview(desired, records, base,
                                                 excluded_accounts=excluded_accounts)
        return preview(desired, records)

    plan = make_plan(current)
    if plan["operations"]["delete"]:
        raise ValueError("Historical records must be retained; record deletion is forbidden")
    result = report(source, base, conflicts, desired, plan, batch)
    if not apply:
        return result
    if expected_hash is not None and expected_hash != plan["hash"]:
        raise RuntimeError("Live preview changed; no target write was made")
    validate_online_evidence(online_evidence, cutoffs)
    evaluate_batch(cutoffs, batch_date, await load_batch_runs(cutoffs, batch_date))
    reread_before_write = await target_rows(client)
    if refresh_history and reread_before_write != current:
        raise RuntimeError("Target changed after full preview; no target write was made")
    if make_plan(reread_before_write)["hash"] != plan["hash"]:
        raise RuntimeError("Target changed after preview; no target write was made")
    if datetime.now(BEIJING).date() != today:
        raise RuntimeError("Sample approval window changed after preview")

    async def verify() -> None:
        after = await target_rows(client)
        if not {row["record_id"] for row in current} <= {row["record_id"] for row in after}:
            raise RuntimeError("Historical record IDs disappeared after write")
        second = make_plan(after)
        if (second["updates"], second["creates"], second["deduplicates"]) != (
            0,
            0,
            0,
        ):
            raise RuntimeError("Post-write preview is not zero-difference")
        if (len(after) != plan["final_count"] or
                second["target_unique"] + second["retained_unscoped_duplicates"] != len(after)):
            raise RuntimeError("Post-write target count or business keys mismatch")
        if refresh_history:
            from scripts.daily_valid_creator_fresh_reconciliation import (
                verify_fresh_projection,
            )

            verify_fresh_projection(desired, current, after, base,
                                    excluded_accounts=excluded_accounts)
        else:
            by_key = {}
            for row in sorted(after, key=lambda row: (
                date_value(row["fields"].get("同意样品日期")) or date.min, row["record_id"])):
                by_key[target_key(row)] = row
            for key, fields in desired.items():
                actual = by_key.get(key)
                if actual is None or any(
                    not equal_field(name, actual["fields"].get(name), value)
                    for name, value in fields.items()
                ):
                    raise RuntimeError("Post-write field values mismatch")
        changed_ids = {record_id for record_id, _ in plan["operations"]["update"]}
        old_by_id = {row["record_id"]: row for row in current}
        after_by_id = {row["record_id"]: row for row in after}
        for record_id in plan["retained_unscoped_ids"]:
            if record_id not in changed_ids and after_by_id.get(record_id) != old_by_id[record_id]:
                raise RuntimeError("Unscoped historical duplicate was modified")
        for row in after:
            record_id = row["record_id"]
            actual_stamp = (row.get("fields") or {}).get("最新更新时间")
            if record_id in changed_ids or record_id not in old_by_id:
                if date_value(actual_stamp) != today:
                    raise RuntimeError("Changed row update date mismatch")
            elif actual_stamp != old_by_id[record_id]["fields"].get("最新更新时间"):
                raise RuntimeError("Unchanged row update date was refreshed")

    if backup_directory:
        from scripts.daily_valid_creator_snapshot import save_snapshot

        result["backup"] = str(save_snapshot(backup_directory, current, plan))
    if scheduled_update:
        validate_daily_valid_creator_source_batch(batch_date, datetime.now(UTC))
    await write_operations(
        client,
        plan["operations"],
        current,
        date_millis(today),
        target_rows,
        verify,
    )
    result["apply"] = {
        "status": "verified",
        "updated": plan["updates"],
        "created": plan["creates"],
        "deduplicated": plan["deduplicates"],
        "retained": plan["retained"],
        "final_records": plan["final_count"],
        "second_preview": [0, 0, 0],
        "confirmed_multi_shop_rows": plan.get("confirmed_multi_shop_rows", []),
        "source_scope": source["accounts"].get("scope"),
        "source_records_captured": source["accounts"].get("captured_total"),
        "source_accounts": source["accounts"]["total"],
        "erp_totals": result.get("erp_totals", {}),
        "history_reconciliation": refresh_history,
        "correction_types": plan.get("correction_types", {}),
        "historical_records": len(plan.get("historical_record_ids", [])),
        "pending_records": len(plan.get("pending_record_ids", [])),
        "protected_record_ids": plan.get("protected_record_ids", []),
        "excluded_accounts": sorted(excluded_accounts),
        "active_projection_rows": plan.get("active_projection_rows", len(desired)),
        "backup": result.get("backup"),
    }
    return result


def validate_sources(feishu, high, low, cutoffs):
    accounts = feishu.get("accounts")
    if feishu.get("source") != "feishu-bitable-readonly" or not isinstance(accounts, dict):
        raise ValueError("Invalid Feishu account source envelope")
    if accounts.get("scope") != "physical_table":
        raise ValueError("Complete physical table source is required; filtered views are forbidden")
    if (accounts.get("physical_table_id") != FEISHU_MERGED_SOURCE.table_id
            or accounts.get("terminal_confirmed") is not True
            or accounts.get("unique_record_ids") is not True
            or accounts.get("captured_total") != accounts.get("final_total")
            or not isinstance(accounts.get("empty_placeholders"), int)
            or accounts.get("total", -1) + accounts["empty_placeholders"] != accounts.get("captured_total")):
        raise ValueError("Complete physical table pagination evidence is required")
    rows = accounts.get("rows")
    if not isinstance(rows, list) or len(rows) != accounts.get("total"):
        raise ValueError("Incomplete Feishu account pagination")
    if any(set(row) != {"accountName", "bdOwner", "sampleApprovedDate", "cooperationShop"} for row in rows):
        raise ValueError("Unexpected Feishu account fields")
    return {"accounts": accounts, **validate_erp_sources(high, low, cutoffs)}


select_base_accounts = select_accounts
