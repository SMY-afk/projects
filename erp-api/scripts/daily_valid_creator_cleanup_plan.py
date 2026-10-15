"""Pure, one-off deletion preview for uniquely proven inactive history rows."""

import hashlib
import json
from collections import Counter
from copy import deepcopy

from scripts.daily_valid_creator_core import account_key
from scripts.daily_valid_creator_fresh_reconciliation import (
    fresh_reconciliation_preview,
)
from scripts.daily_valid_creator_history_identity import (
    DUPLICATE_REASON,
    HISTORY_REASON,
    historical_key,
)


def cleanup_preview(current, desired, base, excluded_accounts=("yana_ok1",)):
    """Exact old tag alone is insufficient; revalidate against complete sources."""
    excluded = {account_key(value) for value in excluded_accounts}
    fresh = fresh_reconciliation_preview(desired, current, base,
                                          excluded_accounts=excluded)
    projected = deepcopy(current)
    projected_by_id = {row["record_id"]: row for row in projected}
    for record_id, changes in fresh["operations"]["update"]:
        projected_by_id[record_id]["fields"].update(changes)
    original_keys = Counter(historical_key(row["fields"]) for row in current)
    projected_keys = Counter(historical_key(row["fields"]) for row in projected)
    skipped, deletes = {}, []
    for row in current:
        record_id, fields = row["record_id"], row["fields"]
        projected_fields = projected_by_id[record_id]["fields"]
        original_key, mapped_key = historical_key(fields), historical_key(projected_fields)
        old_reason = fields.get("保留原因")
        if original_key[0] in excluded:
            reason = "excluded_account"
        elif str(old_reason or "").strip().startswith("待核验"):
            reason = "pending_verification"
        elif old_reason == DUPLICATE_REASON or "重复" in str(old_reason or ""):
            reason = "duplicate_history"
        elif old_reason != HISTORY_REASON:
            reason = "not_exact_authorized_tag"
        elif original_keys[original_key] > 1:
            reason = "duplicate_original_key"
        elif projected_keys[mapped_key] > 1:
            reason = "duplicate_mapped_key"
        elif mapped_key in desired:
            reason = "current_effective_projection"
        elif projected_fields.get("保留原因") != HISTORY_REASON:
            reason = "projected_pending_or_nonhistory"
        elif not mapped_key[1] or mapped_key not in base:
            reason = "source_shop_unverified"
        else:
            deletes.append(record_id)
            continue
        skipped[record_id] = reason
    deletes.sort()
    fingerprint = {
        "delete_ids": deletes,
        "excluded_accounts": sorted(excluded),
        "current": sorted(({"record_id": row["record_id"], "fields": row["fields"]}
                           for row in current), key=lambda row: row["record_id"]),
        "desired": [{"key": list(key), "fields": fields} for key, fields in sorted(desired.items())],
        "master": [{"key": list(key), "source": source} for key, source in sorted(base.items())],
    }
    digest = hashlib.sha256(json.dumps(fingerprint, ensure_ascii=False, sort_keys=True,
                                      separators=(",", ":"), default=str).encode()).hexdigest()
    return {"delete_ids": deletes, "skip_reasons": dict(sorted(skipped.items())), "hash": digest,
            "counts": {"total": len(current), "delete": len(deletes), "retained": len(skipped),
                       "reasons": dict(sorted(Counter(skipped.values()).items())),
                       "duplicate_original_keys": sum(count > 1 for count in original_keys.values()),
                       "duplicate_mapped_keys": sum(count > 1 for count in projected_keys.values())},
            "protected_record_ids": sorted(record_id for record_id, reason in skipped.items()
                                           if reason == "excluded_account"),
            "projected_preview_hash": fresh["hash"],
            "revalidated_active_rows": fresh["active_projection_rows"]}


def _readback_by_id(rows):
    ids = [row.get("record_id") for row in rows]
    if (any(not isinstance(record_id, str) or not record_id for record_id in ids)
            or len(set(ids)) != len(ids)
            or any(not isinstance(row.get("fields"), dict) for row in rows)):
        raise RuntimeError("Cleanup readback record IDs or fields are invalid")
    return {row["record_id"]: row for row in rows}


def verify_cleanup(before, after, delete_ids):
    """Only explicitly authorized IDs may disappear; every remaining field stays."""
    old, new = _readback_by_id(before), _readback_by_id(after)
    requested = list(delete_ids)
    if (any(not isinstance(record_id, str) or not record_id for record_id in requested)
            or len(requested) != len(set(requested)) or not set(requested) <= set(old)):
        raise ValueError("Authorized delete IDs are invalid, repeated or unknown")
    expected = set(old) - set(requested)
    if set(new) != expected:
        raise RuntimeError("Cleanup readback differs from exact authorized record IDs")
    if any(new[record_id]["fields"] != old[record_id]["fields"] for record_id in expected):
        raise RuntimeError("Cleanup changed retained creator fields")
