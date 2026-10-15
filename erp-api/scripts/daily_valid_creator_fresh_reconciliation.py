"""Recompute current rows and correct history without deleting record IDs."""

import hashlib
import json
from collections import Counter, defaultdict
from datetime import date

from scripts.daily_valid_creator_core import BUSINESS_FIELDS, SHOP_ORDER, account_key
from scripts.daily_valid_creator_history_identity import (
    historical_key,
    historical_reason,
    identity_fields,
    inactive_fields,
    keeper_rank,
    matching_master_key,
)
from scripts.daily_valid_creator_shop_rows import shop_record_key
from scripts.daily_valid_creator_sync import equal_field


def _validated_inputs(desired, current, base, excluded):
    ids = [row.get("record_id") for row in current]
    if any(not isinstance(value, str) or not value for value in ids) or len(ids) != len(set(ids)):
        raise ValueError("Target record IDs are invalid or repeated")
    for row in current:
        if not isinstance(row.get("fields"), dict) or not account_key(row["fields"].get("账号名称")):
            raise ValueError("Target creator account identity is invalid")
    if any(not isinstance(key, tuple) or len(key) != 2 for key in (*base, *desired)):
        raise ValueError("Selected master or desired business key is invalid")
    master = {key: value for key, value in base.items() if key[0] not in excluded}
    active = {key: value for key, value in desired.items() if key[0] not in excluded}
    for key, fields in master.items():
        if (not isinstance(key, tuple) or len(key) != 2 or not key[0]
                or key[1] not in (*SHOP_ORDER, "") or account_key(fields.get("account")) != key[0]
                or not isinstance(fields.get("sample_day"), (date, type(None)))):
            raise ValueError("Selected master source has an invalid creator/shop key")
    for key, fields in active.items():
        if key not in master or shop_record_key(fields) != key:
            raise ValueError("Desired identity is absent from declared master source")
        if any(not equal_field(name, fields.get(name), value)
               for name, value in identity_fields(key, master[key]).items()):
            raise ValueError("Desired owner/date differs from declared master source")
        if historical_reason(fields.get("保留原因")):
            raise ValueError("Current desired row cannot be marked as historical")
    return master, active


def fresh_reconciliation_preview(desired, current, base, *, excluded_accounts=()):
    """No mutation, no deletion, no inferred shops, and protected rows untouched."""
    excluded = {account_key(value) for value in excluded_accounts}
    master, active = _validated_inputs(desired, current, base, excluded)
    by_account, mapped, groups = defaultdict(dict), {}, defaultdict(list)
    for key, source in master.items():
        by_account[key[0]][key] = source
    protected = set()
    for row in current:
        account = account_key(row["fields"].get("账号名称"))
        if account in excluded:
            protected.add(row["record_id"])
            continue
        key = matching_master_key(row["fields"], by_account[account])
        mapped[row["record_id"]] = key
        if key is not None:
            groups[key].append(row)
    keepers = {key: max(rows, key=lambda row: keeper_rank(row, key))["record_id"]
               for key, rows in groups.items() if key in active}
    updates, creates, changed_fields = [], [], Counter()
    correction_types = Counter()
    pending, historical, duplicate_ids = [], [], []
    projected_keys = []
    for row in current:
        record_id, fields = row["record_id"], row["fields"]
        if record_id in protected:
            projected_keys.append(historical_key(fields))
            continue
        key = mapped[record_id]
        duplicate = key in active and keepers.get(key) != record_id
        if key in active and not duplicate:
            replacement = active[key]
        else:
            replacement = inactive_fields(fields, key, master.get(key), duplicate=duplicate)
            (pending if key is None else historical).append(record_id)
            if duplicate:
                duplicate_ids.append(record_id)
        changes = {name: value for name, value in replacement.items()
                   if name in BUSINESS_FIELDS and not equal_field(name, fields.get(name), value)}
        if changes:
            updates.append((record_id, changes))
            changed_fields.update(changes.keys())
            for field, label in (("匹配店铺", "shop"), ("BD负责人", "owner"),
                                 ("同意样品日期", "approval_date")):
                if field in changes:
                    correction_types[label] += 1
            if key not in active or duplicate:
                correction_types["historical_status"] += 1
        projected_keys.append(historical_key({**fields, **replacement}))
    for key, fields in sorted(active.items()):
        if key not in keepers:
            creates.append(dict(fields))
            projected_keys.append(key)
    operations = {"update": sorted(updates), "create": creates, "delete": []}
    digest = hashlib.sha256(json.dumps(operations, ensure_ascii=False, sort_keys=True,
                                      separators=(",", ":")).encode()).hexdigest()
    duplicates = len(projected_keys) - len(set(projected_keys))
    return {"operations": operations, "hash": digest, "updates": len(updates),
            "creates": len(creates), "deduplicates": 0, "changed_fields": dict(changed_fields),
            "date_deltas": {}, "retained": len(historical) + len(pending) + len(protected),
            "target_count": len(current), "target_unique": len(set(projected_keys)),
            "final_count": len(current) + len(creates),
            "retained_unscoped_duplicates": duplicates, "retained_unscoped_ids": [],
            "active_projection_rows": len(active), "history_duplicate_rows": len(duplicate_ids),
            "historical_record_ids": sorted(historical), "pending_record_ids": sorted(pending),
            "protected_record_ids": sorted(protected), "correction_types": dict(correction_types),
            "excluded_accounts": sorted(excluded), "fresh_reconciliation": True}


def verify_fresh_projection(desired, before, after, base, *, excluded_accounts=()):
    """Verify exact protected rows, retained IDs, current fields and idempotency."""
    old = {row["record_id"]: row for row in before}
    new = {row["record_id"]: row for row in after}
    if len(new) != len(after) or not set(old) <= set(new):
        raise RuntimeError("Historical record IDs disappeared or were repeated")
    excluded = {account_key(value) for value in excluded_accounts}
    old_protected = {record_id: row for record_id, row in old.items()
                     if account_key(row["fields"].get("账号名称")) in excluded}
    new_protected = {record_id: row for record_id, row in new.items()
                     if account_key(row["fields"].get("账号名称")) in excluded}
    if old_protected != new_protected:
        raise RuntimeError("Protected creator records changed or were created")
    second = fresh_reconciliation_preview(desired, after, base, excluded_accounts=excluded)
    if (second["updates"], second["creates"], second["deduplicates"]) != (0, 0, 0):
        raise RuntimeError("Full reconciliation second preview is not zero-difference")
    current_rows = defaultdict(list)
    for row in after:
        if not historical_reason(row["fields"].get("保留原因")):
            current_rows[historical_key(row["fields"])].append(row["fields"])
    for key, fields in desired.items():
        if key[0] in excluded:
            continue
        matches = current_rows[key]
        if len(matches) != 1 or any(not equal_field(name, matches[0].get(name), value)
                                    for name, value in fields.items()):
            raise RuntimeError("Current creator projection values or uniqueness mismatch")
