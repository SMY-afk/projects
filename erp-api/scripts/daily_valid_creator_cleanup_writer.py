"""Delete frozen one-off IDs once, resolving unknown outcomes by readback only."""

import asyncio
from pathlib import Path

from scripts.daily_valid_creator_cleanup_plan import verify_cleanup
from scripts.daily_valid_creator_cleanup_snapshot import (
    exclusive_json,
    load_cleanup_snapshot,
)
from scripts.daily_valid_creator_core import account_key
from scripts.daily_valid_creator_history_identity import HISTORY_REASON
from scripts.daily_valid_creator_io import BASE, TABLE


class CleanupAuditRequired(RuntimeError):
    def __init__(self, audit_path, completed_ids):
        super().__init__("Cleanup stopped; manual audit is required")
        self.audit_path = Path(audit_path)
        self.completed_ids = tuple(sorted(completed_ids))


async def _stable_read(client, reread):
    first = await reread(client)
    second = await reread(client)
    verify_cleanup(first, second, [])
    return second


def _validate_batch(current, batch, approved, excluded):
    by_id = {row["record_id"]: row for row in current}
    if len(batch) != len(set(batch)) or not set(batch) <= approved or not set(batch) <= set(by_id):
        raise ValueError("Cleanup requested IDs are outside frozen approved scope")
    for record_id in batch:
        fields = by_id[record_id]["fields"]
        account = account_key(fields.get("账号名称"))
        if (not account or account in excluded
                or fields.get("保留原因") != HISTORY_REASON):
            raise ValueError("Cleanup requested record changed or is protected")


def _response_verified(response, batch):
    records = response.get("records") if isinstance(response, dict) else None
    return (isinstance(records, list) and len(records) == len(batch)
            and {row.get("record_id") for row in records} == set(batch)
            and all(row.get("deleted") is True for row in records))


async def write_cleanup(client, snapshot_receipt, reread, *, excluded_accounts=("yana_ok1",),
                        chunk_size=100, before_batch=None):
    if type(chunk_size) is not int or not 1 <= chunk_size <= 100:
        raise ValueError("Cleanup batch size must be an integer from 1 to 100")
    data = load_cleanup_snapshot(snapshot_receipt, excluded_accounts)
    baseline = data["current"]
    approved = frozenset(data["plan"]["delete_ids"])
    frozen_ids = tuple(sorted(approved))
    excluded = {account_key(value) for value in excluded_accounts} | {"yana_ok1"}
    baseline_ids = {row["record_id"] for row in baseline}
    _validate_batch(baseline, frozen_ids, approved, excluded)
    completed, unknown_count, events = set(), 0, []
    audit = {"snapshot_sha256": snapshot_receipt["sha256"],
             "snapshot_path": str(snapshot_receipt["path"]), "authorized_ids": list(frozen_ids),
             "events": events}
    try:
        for offset in range(0, len(frozen_ids), chunk_size):
            load_cleanup_snapshot(snapshot_receipt, excluded_accounts)
            batch = list(frozen_ids[offset:offset + chunk_size])
            if before_batch is not None:
                await before_batch()
            # Slow gates must precede the final target reads so a change during
            # a health/source check is caught before the non-retried DELETE.
            current = await _stable_read(client, reread)
            verify_cleanup(baseline, current, completed)
            _validate_batch(current, batch, approved, excluded)
            event = {"requested_ids": batch, "response_verified": False}
            events.append(event)
            try:
                response = await client.batch_records(BASE, TABLE, "batch_delete", batch,
                                                      retry_mode="none")
                event["response_verified"] = _response_verified(response, batch)
            except (Exception, asyncio.CancelledError) as error:  # noqa: BLE001 - Resolve every unknown delete outcome.
                event["error_type"] = type(error).__name__
                event["interrupted"] = isinstance(error, asyncio.CancelledError)
            after = await _stable_read(client, reread)
            observed_ids = {row["record_id"] for row in after}
            removed = baseline_ids - observed_ids
            event["observed_removed_ids"] = sorted(removed)
            if not completed <= removed or not removed <= completed | set(batch):
                raise RuntimeError("Cleanup readback changed IDs outside current batch")
            verify_cleanup(baseline, after, removed)
            event["removed_ids"] = sorted(removed - completed)
            event["outcome"] = ("committed" if removed == completed | set(batch)
                                else "partial" if removed != completed else "not_applied")
            completed = removed
            if event["outcome"] != "committed":
                raise RuntimeError("Cleanup batch did not fully commit; no replay is allowed")
            unknown_count += not event["response_verified"]
            if event.get("interrupted"):
                raise RuntimeError("Cleanup was interrupted; no following batch is permitted")
        final = await _stable_read(client, reread) if not frozen_ids else after
        verify_cleanup(baseline, final, frozen_ids)
    except (Exception, asyncio.CancelledError) as error:  # noqa: BLE001 - Persist audit before stopping any failure.
        audit.update(status="audit_required", completed_ids=sorted(completed),
                     error_type=type(error).__name__)
        receipt = exclusive_json(Path(snapshot_receipt["path"]).parent,
                                 "daily-creator-cleanup-audit", audit)
        raise CleanupAuditRequired(receipt["path"], completed) from None
    audit.update(status="verified", completed_ids=sorted(completed))
    receipt = exclusive_json(Path(snapshot_receipt["path"]).parent,
                             "daily-creator-cleanup-audit", audit)
    return {"status": "verified", "deleted": len(completed), "deleted_ids": sorted(completed),
            "unknown_outcomes_confirmed": unknown_count, "audit_path": str(receipt["path"]),
            "snapshot_path": str(snapshot_receipt["path"]),
            "snapshot_sha256": snapshot_receipt["sha256"]}
