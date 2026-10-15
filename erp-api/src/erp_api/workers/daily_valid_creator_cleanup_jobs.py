"""Explicit one-time cleanup in the existing independent serial daily worker."""

from __future__ import annotations

import json
import os
import re

from scripts.daily_valid_creator_core import account_key

CLEANUP_SCOPE = "daily-valid-creator-exact-inactive-history-v1"


def grant_key(owner):
    if not isinstance(owner, str) or re.fullmatch(r"[0-9a-f]{32}", owner) is None:
        raise ValueError("Cleanup grant owner must be a unique nonce")
    return f"daily-valid-creators:cleanup:{owner}:grant"


async def _read_grant(redis, owner, apply):
    key = grant_key(owner)
    try:
        value = json.loads(await redis.get(key))
    except (TypeError, ValueError) as error:
        raise ValueError("Explicit cleanup grant is missing or invalid") from error
    if not isinstance(value, dict):
        raise TypeError("Explicit cleanup grant is invalid")
    accounts = value.get("excluded_accounts")
    if (value.get("scope") != CLEANUP_SCOPE or value.get("owner") != owner
            or value.get("mode") != ("apply" if apply else "preview")
            or not isinstance(accounts, list) or not accounts
            or any(not isinstance(account, str) or not account_key(account)
                   for account in accounts)
            or "yana_ok1" not in {account_key(account) for account in accounts}):
        raise ValueError("Explicit cleanup grant scope or protected accounts are invalid")
    expected_hash = value.get("expected_plan_hash")
    if apply and (not isinstance(expected_hash, str)
                  or re.fullmatch(r"[0-9a-f]{64}", expected_hash) is None):
        raise ValueError("Explicit cleanup apply grant requires a frozen preview hash")
    return value, frozenset(account_key(account) for account in accounts)


async def cleanup_daily_valid_creators_job(ctx, owner: str, apply: bool = False):
    """Consume each explicitly authorized phase once; never alter daily receipts."""
    from scripts.daily_valid_creator_cleanup_pipeline import cleanup

    redis = ctx["redis"]
    grant, excluded = await _read_grant(redis, owner, apply)
    prefix = f"daily-valid-creators:cleanup:{owner}"
    phase = "apply" if apply else "preview"
    # Deliberately no expiration: unknown deletes cannot be retried automatically.
    if not await redis.set(prefix + f":{phase}:claimed", owner, nx=True):
        return {"status": "already_claimed"}
    try:
        result = await cleanup(
            ctx, apply=apply, expected_hash=grant.get("expected_plan_hash"),
            excluded_accounts=excluded,
            backup_directory=os.getenv("DAILY_VALID_CREATOR_BACKUP_DIR",
                                       "/app/runtime/daily-creator-backups"),
            export_url=os.getenv("AFFILIATE_EXPORT_URL",
                                 "http://127.0.0.1:8080/api/internal/affiliate-center/"),
        )
        await redis.set(prefix + f":{phase}:result",
                        json.dumps(result, ensure_ascii=False, default=str))
        return result
    except Exception as error:
        failure = {"error_type": type(error).__name__, "phase": phase}
        audit_path = getattr(error, "audit_path", None)
        if audit_path is not None:
            failure.update(audit_path=str(audit_path),
                           completed_ids=list(getattr(error, "completed_ids", ())))
        await redis.set(prefix + f":{phase}:failure", json.dumps(failure))
        raise
