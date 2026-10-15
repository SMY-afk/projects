"""One-off, fully backed-up removal of exactly proven inactive creator history."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import httpx

from erp_api.core.config import get_settings
from erp_api.infrastructure.health import probe_dependencies
from erp_api.routers.health import _sample_sync_config_status
from erp_api.services.daily_valid_creator_schedule import (
    daily_valid_creator_source_batch,
    validate_daily_valid_creator_source_batch,
)
from erp_api.workers.analytics_jobs import _now
from erp_api.workers.daily_valid_creator_jobs import _ready_snapshot
from scripts.daily_valid_creator_accounts import select_accounts
from scripts.daily_valid_creator_batch import evaluate_batch, load_batch_runs
from scripts.daily_valid_creator_cleanup_plan import cleanup_preview, verify_cleanup
from scripts.daily_valid_creator_cleanup_snapshot import (
    exclusive_json,
    save_cleanup_snapshot,
)
from scripts.daily_valid_creator_cleanup_writer import (
    CleanupAuditRequired,
    write_cleanup,
)
from scripts.daily_valid_creator_core import BEIJING, account_key
from scripts.daily_valid_creator_io import (
    BASE,
    EXPORT_URL,
    FIELD_TYPES,
    TABLE,
    feishu_client,
    fetch_sources,
    target_rows,
    verify_target_identity,
)
from scripts.daily_valid_creator_pipeline import validate_sources
from scripts.daily_valid_creator_report_gate import missing_creator_reports
from scripts.daily_valid_creator_sample import sample_window_for_day
from scripts.daily_valid_creator_shop_rows import desired_shop_rows

IDENTITY = {"app_token": BASE, "base_name": "样品--副本", "table_id": TABLE,
            "table_name": "（每日更新）有效达人"}


def content_hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                      separators=(",", ":"), default=str).encode()).hexdigest()


async def require_cleanup_health(ctx, export_url):
    """API health alone can hide a disabled sample role; require both checks."""
    url = urlsplit(export_url)
    ready_url = urlunsplit((url.scheme, url.netloc, "/readyz", "", ""))
    async with httpx.AsyncClient(timeout=20, trust_env=False) as http:
        response = await http.get(ready_url)
    if response.status_code != 200 or response.json().get("status") != "ok":
        raise RuntimeError("Cleanup requires HTTP 200 healthy /readyz")
    settings = get_settings()
    local_config = _sample_sync_config_status(settings)
    api_config = response.json().get("dependencies", {}).get("sample_sync_config")
    if local_config not in {"ok", "disabled"} or api_config not in {"ok", "disabled"}:
        raise RuntimeError("Cleanup sample role configuration is unavailable")
    # Daily/API roles can intentionally disable sample configuration. Inspect
    # the actual shared schema and running sample worker rather than fake 'ok'.
    dependencies = await probe_dependencies(ctx["database"], settings.redis_url,
                                           sample_sync_enabled=True)
    if any(dependencies.get(key) != "ok" for key in
           ("database", "redis", "sample_schema", "sample_worker")):
        raise RuntimeError("Cleanup actual sample dependencies are unhealthy")
    return {"api_sample_config": api_config, "daily_sample_config": local_config,
            "forced_sample_dependencies": dependencies}


async def require_cleanup_sources(ctx, export_url, *, expected=None):
    """No old success receipt can substitute fresh observations and full batches."""
    health = await require_cleanup_health(ctx, export_url)
    now = _now(ctx)
    batch_date = daily_valid_creator_source_batch(now)
    snapshot = await _ready_snapshot(ctx, now)
    if snapshot is None:
        raise RuntimeError("Cleanup direct five-shop source evidence is not ready")
    cutoffs, evidence, fingerprint = snapshot
    if expected is not None and (cutoffs != expected[0] or fingerprint != expected[2]
                                 or batch_date != expected[3]):
        raise RuntimeError("Cleanup source dates or authorization scope changed")
    validate_daily_valid_creator_source_batch(batch_date, now)
    batch = evaluate_batch(cutoffs, batch_date, await load_batch_runs(cutoffs, batch_date))
    if await missing_creator_reports(ctx["database"], cutoffs):
        raise RuntimeError("Cleanup required creator reports are incomplete")
    return cutoffs, evidence, fingerprint, batch_date, {**batch, "health": health}


async def read_target_schema(client):
    """Keep every field property and prove complete stable field pagination."""
    token = await client.tenant_access_token()
    page_token, cursors, fields, total = "", set(), [], None
    while True:
        params = {"page_size": 100}
        if page_token:
            params["page_token"] = page_token
        envelope = await client.request_json(
            "GET", f"/open-apis/bitable/v1/apps/{BASE}/tables/{TABLE}/fields",
            retry_mode="idempotent", headers={"Authorization": "Bearer " + token},
            params=params,
        )
        data = envelope.get("data", {})
        if total is None:
            total = data.get("total")
        if (not isinstance(total, int) or isinstance(total, bool) or total < 0
                or data.get("total") != total or not isinstance(data.get("items"), list)
                or not isinstance(data.get("has_more"), bool)):
            raise ValueError("Cleanup field pagination evidence is invalid")
        fields.extend(data["items"])
        if not data["has_more"]:
            break
        page_token = data.get("page_token")
        if not isinstance(page_token, str) or not page_token or page_token in cursors:
            raise ValueError("Cleanup field pagination cursor is repeated or missing")
        cursors.add(page_token)
    ids = [field.get("field_id") for field in fields]
    names = [field.get("field_name") for field in fields]
    if (len(fields) != total or len(set(ids)) != total or len(set(names)) != total
            or any(not isinstance(value, str) or not value for value in ids)):
        raise ValueError("Cleanup field pagination is incomplete or repeated")
    actual = {field["field_name"]: field.get("type") for field in fields}
    if actual != FIELD_TYPES:
        raise ValueError("Cleanup target field schema mismatch")
    return sorted(fields, key=lambda field: field["field_id"])


def _projection(raw, cutoffs, sample_window):
    source = validate_sources(*raw, cutoffs)
    base, conflicts = select_accounts(source["accounts"]["rows"], sample_window)
    desired = desired_shop_rows(base, source["high"], source["low"],
                                source["windows"], sample_window)
    return source, base, desired, conflicts


async def cleanup(
    ctx, *, apply=False, expected_hash=None, export_url=EXPORT_URL,
    backup_directory, excluded_accounts=frozenset({"yana_ok1"}),
):
    """Runs only inside the original independent, single-job daily worker."""
    excluded = frozenset(account_key(value) for value in excluded_accounts)
    if "yana_ok1" not in excluded:
        raise ValueError("Cleanup must protect yana_ok1")
    if apply and (not isinstance(expected_hash, str) or len(expected_hash) != 64):
        raise ValueError("Cleanup apply requires an authorized preview hash")
    snapshot = await require_cleanup_sources(ctx, export_url)
    cutoffs, evidence, fingerprint, batch_date, batch = snapshot
    today = _now(ctx).astimezone(BEIJING).date()
    sample_window = sample_window_for_day(today)
    raw = await fetch_sources(cutoffs, export_url=export_url)
    source, base, desired, conflicts = _projection(raw, cutoffs, sample_window)
    client = feishu_client()
    await verify_target_identity(client)
    schema = await read_target_schema(client)
    current = await target_rows(client)
    plan = cleanup_preview(current, desired, base, excluded_accounts=excluded)
    if apply and plan["hash"] != expected_hash:
        raise RuntimeError("Authorized preview hash changed; no target deletion was made")
    proof = {"batch": batch, "batch_date": batch_date, "online": evidence,
             "fingerprint": fingerprint,
             "cutoffs": cutoffs, "source_content_hash": content_hash(raw),
             "source_records": source["accounts"].get("captured_total"),
             "master_pagination": {key: value for key, value in source["accounts"].items()
                                   if key != "rows"},
             "erp_windows": source["windows"],
             "erp_totals": {
                 name: [{"shop": row["shopName"], "totals": row["totals"],
                         "source_windows": row.get("sourceWindows")}
                        for row in payload.get("shops", [])]
                 for name, payload in zip(("high", "low"), raw[1:], strict=True)},
             "conflict_count": conflicts, "sample_window": sample_window}
    receipt = save_cleanup_snapshot(
        backup_directory, identity=IDENTITY, schema=schema, current=current,
        plan=plan, source_evidence=proof, desired=desired, base=base,
        excluded_accounts=excluded,
    )
    await require_cleanup_sources(ctx, export_url, expected=snapshot)
    repeated = await fetch_sources(cutoffs, export_url=export_url)
    _, second_base, second_desired, _ = _projection(repeated, cutoffs, sample_window)
    if content_hash(repeated) != content_hash(raw):
        raise RuntimeError("Source content changed after complete backup")
    await verify_target_identity(client)
    if await read_target_schema(client) != schema:
        raise RuntimeError("Target schema changed after complete backup")
    reread = await target_rows(client)
    if content_hash(reread) != content_hash(current):
        raise RuntimeError("Target records changed after complete backup")
    second = cleanup_preview(reread, second_desired, second_base, excluded_accounts=excluded)
    if second["hash"] != plan["hash"]:
        raise RuntimeError("Cleanup preview changed after complete backup")

    async def before_batch():
        if _now(ctx).astimezone(BEIJING).date() != today:
            raise RuntimeError("Cleanup sample approval day changed")
        await require_cleanup_sources(ctx, export_url, expected=snapshot)

    result = {"preview": plan, "backup": receipt, "source_evidence": proof}
    if apply:
        result["apply"] = await write_cleanup(
            client, receipt, target_rows, excluded_accounts=excluded,
            before_batch=before_batch,
        )
        try:
            await before_batch()
            if await read_target_schema(client) != schema:
                raise RuntimeError("Target schema changed during cleanup")
            after = await target_rows(client)
            verify_cleanup(current, after, plan["delete_ids"])
            final = cleanup_preview(after, desired, base, excluded_accounts=excluded)
            if final["delete_ids"]:
                raise RuntimeError("Cleanup post-readback preview is not zero-difference")
            result["apply"].update(final_records=len(after), second_preview_delete=0,
                                    protected_record_ids=plan["protected_record_ids"])
        except (Exception, asyncio.CancelledError) as error:  # noqa: BLE001 -- audit known deletes
            completed = result["apply"].get("deleted_ids", plan["delete_ids"])
            audit = exclusive_json(Path(receipt["path"]).parent,
                "daily-creator-cleanup-post-verification", {
                    "status": "post_verification_failed", "error_type": type(error).__name__,
                    "completed_ids": completed, "snapshot_sha256": receipt["sha256"],
                    "writer_audit_path": result["apply"].get("audit_path"),
                })
            raise CleanupAuditRequired(audit["path"], completed) from None
    return result
