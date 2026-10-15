"""Explicit one-off current-table updates; keep scheduled receipts unchanged."""

import json
import os
import re

from erp_api.workers.daily_valid_creator_jobs import _excluded_accounts
from scripts.daily_valid_creator_core import account_key

SCOPE = "daily-valid-creator-current-update-once-v1"


def grant_key(owner):
    if not isinstance(owner, str) or re.fullmatch(r"[0-9a-f]{32}", owner) is None:
        raise ValueError("Manual update owner must be a unique nonce")
    return f"daily-valid-creators:manual-update:{owner}:grant"


async def read_grant(redis, owner):
    raw = await redis.get(grant_key(owner))
    if raw is None:
        raise ValueError("Explicit current-update grant is missing")
    grant = json.loads(raw)
    if not isinstance(grant, dict) or grant.get("scope") != SCOPE or grant.get("owner") != owner:
        raise ValueError("Explicit current-update scope is invalid")
    accounts = grant.get("excluded_accounts")
    if (not isinstance(accounts, list) or not accounts
            or any(not isinstance(value, str) or not account_key(value) for value in accounts)):
        raise ValueError("Current-update protected accounts are invalid")
    excluded = frozenset(account_key(value) for value in accounts)
    if "yana_ok1" not in excluded or not await _excluded_accounts(redis) <= excluded:
        raise ValueError("Current-update grant must retain existing account protection")
    if (not isinstance(grant.get("expected_hash"), str)
            or re.fullmatch(r"[0-9a-f]{64}", grant["expected_hash"]) is None
            or not isinstance(grant.get("source_backup"), dict)):
        raise ValueError("Current-update requires a frozen complete preview")
    receipt = grant["source_backup"]
    if (not isinstance(receipt.get("path"), str)
            or not receipt["path"].startswith("/opt/erp/backups/daily-creator-cleanup-snapshot-")
            or re.fullmatch(r"[0-9a-f]{64}", str(receipt.get("sha256") or "")) is None):
        raise ValueError("Current-update snapshot path or digest is invalid")
    return grant, excluded


async def update_current_daily_creators_job(ctx, owner):
    from scripts.daily_valid_creator_cleanup_pipeline import (
        content_hash, require_cleanup_sources,
    )
    from scripts.daily_valid_creator_cleanup_snapshot import load_cleanup_snapshot, snapshot_projection
    from scripts.daily_valid_creator_fresh_reconciliation import fresh_reconciliation_preview
    from scripts.daily_valid_creator_io import fetch_sources
    from scripts.daily_valid_creator_pipeline import reconcile

    redis = ctx["redis"]
    grant, excluded = await read_grant(redis, owner)
    prefix = grant_key(owner).removesuffix(":grant")
    if not await redis.set(prefix + ":claimed", owner, nx=True):
        return {"status": "already_claimed"}
    try:
        data = load_cleanup_snapshot(grant["source_backup"], excluded)
        desired, base = snapshot_projection(data)
        preview = fresh_reconciliation_preview(desired, data["current"], base,
                                               excluded_accounts=excluded)
        if preview["hash"] != grant["expected_hash"]:
            raise RuntimeError("Current-update preview does not match authorized backup")
        export_url = os.getenv("AFFILIATE_EXPORT_URL",
                               "http://127.0.0.1:8080/api/internal/affiliate-center/")
        cutoffs, evidence, fingerprint, batch_date, _ = await require_cleanup_sources(ctx, export_url)
        proof = data["source_evidence"]
        if (fingerprint != proof["fingerprint"] or str(batch_date) != str(proof["batch_date"])
                or content_hash(cutoffs) != content_hash(proof["cutoffs"])):
            raise RuntimeError("Current-update source dates or scope changed")
        raw = await fetch_sources(cutoffs, export_url=export_url)
        if content_hash(raw) != proof["source_content_hash"]:
            raise RuntimeError("Current-update source content changed; re-preview required")
        result = await reconcile(
            cutoffs, batch_date, evidence, apply=True, expected_hash=grant["expected_hash"],
            export_url=export_url, refresh_history=True, excluded_accounts=excluded,
            backup_directory=os.getenv("DAILY_VALID_CREATOR_BACKUP_DIR", "/opt/erp/backups"),
            scheduled_update=True,
            expected_source_hash=proof["source_content_hash"],
            expected_target_hash=content_hash(data["current"]),
        )
        await redis.set(prefix + ":result", json.dumps(result, ensure_ascii=False, default=str))
        return result["apply"]
    except Exception as error:
        await redis.set(prefix + ":failure", json.dumps({"error_type": type(error).__name__}))
        raise
