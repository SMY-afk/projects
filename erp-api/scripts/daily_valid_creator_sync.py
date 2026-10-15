"""Preview and reconcile fixed Feishu creator sources with the daily sample table."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from collections import Counter, defaultdict
from datetime import UTC, date, datetime

from erp_api.services.affiliate_schedule_queries import latest_due_schedule_date
from scripts.daily_valid_creator_core import (
    BEIJING,
    BUSINESS_FIELDS,
    SHOP_LINES,
    amount,
    date_value,
)
from scripts.daily_valid_creator_dates import parse_shop_cutoffs
from scripts.daily_valid_creator_online import load_online_evidence
from scripts.daily_valid_creator_shop_rows import shop_record_key


def equal_field(name: str, existing: object, desired: object) -> bool:
    if name in {"最近有效日期", "同意样品日期"}:
        return date_value(existing) == date_value(desired)
    if name in {"业绩", "视频数", "直播数"}:
        return amount(existing) == amount(desired)
    return str(existing or "").strip() == str(desired or "").strip()


def target_key(row: dict) -> tuple[str, str]:
    return shop_record_key(row.get("fields") or {})


def preview(desired: dict, current: list[dict]) -> dict:
    if any("；" in str((row.get("fields") or {}).get("匹配店铺") or "") for row in current):
        from scripts.daily_valid_creator_schema_plan import migration_preview

        return migration_preview(desired, current, preview)
    from scripts.daily_valid_creator_blank_shop_adoption import adoption_preview

    adopted = adoption_preview(desired, current, preview)
    if adopted is not None:
        return adopted
    for key, fields in desired.items():
        if (
            not isinstance(key, tuple)
            or len(key) != 2
            or not key[0]
            or key
            != shop_record_key(fields)
        ):
            raise ValueError("Desired source has an invalid business key")
    grouped = defaultdict(list)
    for row in current:
        key = target_key(row)
        if not key[0]:
            raise ValueError("Target has a blank or invalid business key")
        grouped[key].append(row)
    duplicate_ids = []
    retained_unscoped_ids = []
    keepers = {}
    for key, records in grouped.items():
        ordered = sorted(
            records,
            key=lambda r: (
                date_value((r.get("fields") or {}).get("同意样品日期")) or date.min,
                str(r.get("record_id") or ""),
            ),
        )
        keepers[key] = ordered[-1]
        if key[1]:
            duplicate_ids.extend(r["record_id"] for r in ordered[:-1])
        else:
            retained_unscoped_ids.extend(r["record_id"] for r in ordered[:-1])
    updates = []
    creates = []
    changed_fields = Counter()
    date_deltas = defaultdict(Counter)
    for key, fields in desired.items():
        if key not in keepers:
            creates.append(fields)
        else:
            changes = [
                name
                for name in BUSINESS_FIELDS
                if not equal_field(
                    name, keepers[key]["fields"].get(name), fields.get(name)
                )
            ]
            if changes:
                changed_fields.update(changes)
                for name in ("最近有效日期", "同意样品日期"):
                    if name in changes:
                        before = date_value(keepers[key]["fields"].get(name))
                        after = date_value(fields.get(name))
                        if before and after:
                            label = str((after - before).days)
                        elif after:
                            label = "empty_to_date"
                        else:
                            label = "date_to_empty"
                        date_deltas[name][label] += 1
                updates.append(
                    (
                        keepers[key]["record_id"],
                        {name: fields.get(name) for name in changes},
                    )
                )
    operations = {
        "update": sorted(updates, key=lambda pair: pair[0]),
        "create": sorted(
            creates, key=shop_record_key
        ),
        "delete": sorted(duplicate_ids),
    }
    digest = hashlib.sha256(
        json.dumps(
            operations, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    return {
        "operations": operations,
        "hash": digest,
        "updates": len(updates),
        "creates": len(creates),
        "deduplicates": len(duplicate_ids),
        "changed_fields": dict(changed_fields),
        "date_deltas": {name: dict(counts) for name, counts in date_deltas.items()},
        "retained": len(set(keepers) - set(desired)) + len(retained_unscoped_ids),
        "retained_unscoped_duplicates": len(retained_unscoped_ids),
        "retained_unscoped_ids": retained_unscoped_ids,
        "target_count": len(current),
        "target_unique": len(keepers),
        "final_count": len(keepers) + len(creates) + len(retained_unscoped_ids),
    }


def report(
    source: dict,
    base: dict,
    conflicts: int,
    desired: dict,
    plan: dict,
    batch: dict,
) -> dict:
    return {
        "batch_gate": batch,
        "shop_windows": {
            name: {
                resource: [str(start), str(end)]
                for resource, (start, end) in source["windows"][name].items()
            }
            for name in SHOP_LINES
        },
        "feishu_totals": {"accounts": source["accounts"]["total"]},
        "erp_totals": {
            name: {
                "creators": source["high"][name]["totals"]["creators"],
                "videos": source["low"][name]["totals"]["videos"],
                "liveAccounts": source["high"][name]["totals"]["liveAccounts"],
            }
            for name in SHOP_LINES
        },
        "base_unique": len(base),
        "bd_conflicts_resolved": conflicts,
        "desired_unique": len(desired),
        "preview": {k: v for k, v in plan.items() if k != "operations"},
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--shop-cutoff",
        action="append",
        required=True,
        metavar="NAME,CREATOR_END,VIDEO_END",
        help="NAME,CREATOR_END,VIDEO_END,LIVE_END; repeat for five shops",
    )
    parser.add_argument("--apply-hash")
    parser.add_argument("--online-evidence-json")
    parser.add_argument("--batch-date", type=date.fromisoformat)
    args = parser.parse_args()
    cutoffs = parse_shop_cutoffs(args.shop_cutoff, today=datetime.now(BEIJING).date())
    if not args.online_evidence_json:
        raise ValueError(
            "Fresh direct TK online evidence is required for preview and apply"
        )
    evidence = load_online_evidence(args.online_evidence_json, cutoffs)
    batch_date = args.batch_date or latest_due_schedule_date(datetime.now(UTC))
    from scripts.daily_valid_creator_pipeline import reconcile

    result = await reconcile(
        cutoffs,
        batch_date,
        evidence,
        apply=bool(args.apply_hash),
        expected_hash=args.apply_hash,
    )
    print(
        json.dumps(result, ensure_ascii=False),
        flush=True,
    )


if __name__ == "__main__":
    asyncio.run(main())
