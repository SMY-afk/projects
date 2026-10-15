"""Queue the Feishu creator reconciliation as soon as the full batch is ready."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import date, datetime
from uuid import uuid4

from erp_api.core.config import get_settings
from erp_api.services.affiliate_capture_health import AffiliateCaptureHealthRepository
from erp_api.services.affiliate_local_export_service import TARGET_SHOPS
from erp_api.services.daily_valid_creator_schedule import (
    daily_valid_creator_source_batch,
)
from erp_api.services.feishu_creator_export_service import FEISHU_MERGED_SOURCE
from erp_api.workers.affiliate_live_observation import latest_recent_live_observation
from erp_api.workers.affiliate_live_schedule import _active_live_shops
from erp_api.workers.analytics_jobs import _now

_SOURCE_NAMES = {item.source_name: item.business_name for item in TARGET_SHOPS}
QUEUE_NAME = "arq:daily-valid-creators"
SYNC_RULE_VERSION = "sample-approval-full-history-reconciliation-v5"
EXCLUDED_ACCOUNTS_KEY = "daily-valid-creators:excluded-accounts"
FAILED_SYNC_COOLDOWN_SECONDS = 900
SOURCE_NOT_READY_COOLDOWN_SECONDS = 300
_UNLOCK_IF_OWNED = (
    "if redis.call('get', KEYS[1]) == ARGV[1] "
    "then return redis.call('del', KEYS[1]) else return 0 end"
)


async def _set_cooldown(redis, batch_prefix, prefix, seconds):
    for key in {batch_prefix + ":cooldown", prefix + ":cooldown"}:
        await redis.set(key, "1", ex=seconds)


async def _batch_sync_succeeded(redis, batch_prefix):
    async for key in redis.scan_iter(match=batch_prefix + ":*:success", count=20):
        if await redis.get(key) in ("1", b"1"):
            return True
    return False


async def _excluded_accounts(redis) -> frozenset[str]:
    from scripts.daily_valid_creator_core import account_key

    raw = await redis.get(EXCLUDED_ACCOUNTS_KEY)
    if raw is None:
        return frozenset()
    try:
        accounts = json.loads(raw)
    except (ValueError, TypeError) as error:
        raise ValueError("Invalid daily creator exclusion configuration") from error
    if (not isinstance(accounts, list)
            or any(not isinstance(value, str) or not account_key(value) for value in accounts)):
        raise ValueError("Invalid daily creator exclusion configuration")
    return frozenset(account_key(value) for value in accounts)


async def _ready_snapshot(ctx, now: datetime):
    from scripts.daily_valid_creator_online import validate_online_evidence

    tenant_id = get_settings().affiliate_export_tenant_id
    if tenant_id is None:
        raise RuntimeError("Affiliate export tenant is not configured")
    shops = [
        shop
        for shop in await _active_live_shops(ctx["database"])
        if shop.tenant_id == tenant_id and shop.source_name in _SOURCE_NAMES
    ]
    if len(shops) != len(TARGET_SHOPS) or {shop.source_name for shop in shops} != set(
        _SOURCE_NAMES
    ):
        return None
    health_repository = AffiliateCaptureHealthRepository(ctx["redis"])
    cutoffs = {}
    evidence_rows = []
    for shop in shops:
        health = await health_repository.get(tenant_id, shop.shop_id)
        if health.state != "online" or not health.session_available:
            return None
        creator = await health_repository.observed_evidence_for(
            tenant_id, shop.shop_id, "creators", now=now
        )
        video = await health_repository.observed_evidence_for(
            tenant_id, shop.shop_id, "videos", now=now
        )
        live = await health_repository.observed_evidence_for(
            tenant_id, shop.shop_id, "liveAccounts", now=now
        )
        if live is None:
            live = await latest_recent_live_observation(
                ctx["database"], tenant_id, shop.shop_id, now=now
            )
        if creator is None or video is None or live is None:
            return None
        name = _SOURCE_NAMES[shop.source_name]
        cutoffs[name] = {
            "creators": creator[0],
            "videos": video[0],
            "liveAccounts": live[0],
        }
        evidence_rows.append(
            {
                "shop": name,
                "observed_at": min(creator[1], video[1], live[1]).isoformat(),
                "creators": creator[0].isoformat(),
                "videos": video[0].isoformat(),
                "liveAccounts": live[0].isoformat(),
            }
        )
    evidence = {"source": "direct_tk_sources", "shops": evidence_rows}
    validate_online_evidence(evidence, cutoffs, now=now)
    fingerprint = hashlib.sha256(
        json.dumps(
            {
                "rule_version": SYNC_RULE_VERSION,
                "excluded_accounts": sorted(await _excluded_accounts(ctx["redis"])),
                "prerequisite_source": (
                    FEISHU_MERGED_SOURCE.app_token,
                    FEISHU_MERGED_SOURCE.table_id,
                    "physical_table",
                ),
                "cutoffs": {
                    name: {key: value.isoformat() for key, value in dates.items()}
                    for name, dates in sorted(cutoffs.items())
                },
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()[:20]
    return cutoffs, evidence, fingerprint


async def enqueue_due_valid_creator_syncs(ctx) -> int:
    """Completion check: a one-minute scan also covers missed notifications."""
    from scripts.daily_valid_creator_batch import evaluate_batch, load_batch_runs
    from scripts.daily_valid_creator_report_gate import missing_creator_reports

    now = _now(ctx)
    batch_date = daily_valid_creator_source_batch(now)
    batch_prefix = f"valid-creator-sync:{batch_date:%Y%m%d}"
    redis = ctx["redis"]
    if await _batch_sync_succeeded(redis, batch_prefix):
        return 0
    if await redis.get(batch_prefix + ":cooldown"):
        return 0
    snapshot = await _ready_snapshot(ctx, now)
    if snapshot is None:
        await _set_cooldown(redis, batch_prefix, batch_prefix,
                            SOURCE_NOT_READY_COOLDOWN_SECONDS)
        return 0
    cutoffs, _, fingerprint = snapshot
    prefix = f"{batch_prefix}:{fingerprint}"
    if await redis.get(prefix + ":cooldown"):
        return 0
    try:
        evaluate_batch(cutoffs, batch_date, await load_batch_runs(cutoffs, batch_date))
    except ValueError:
        await _set_cooldown(redis, batch_prefix, prefix, SOURCE_NOT_READY_COOLDOWN_SECONDS)
        return 0
    if await missing_creator_reports(ctx["database"], cutoffs):
        await _set_cooldown(redis, batch_prefix, prefix, SOURCE_NOT_READY_COOLDOWN_SECONDS)
        return 0
    owner = uuid4().hex
    if not await redis.set(prefix + ":lock", owner, nx=True, ex=3600):
        return 0
    try:
        job = await redis.enqueue_job(
            "sync_daily_valid_creator_job",
            batch_date.isoformat(),
            fingerprint,
            owner,
            _job_id=prefix + ":" + owner,
            _queue_name=QUEUE_NAME,
        )
        if job is None:
            await redis.eval(_UNLOCK_IF_OWNED, 1, prefix + ":lock", owner)
            return 0
        return 1
    except Exception:
        await redis.eval(_UNLOCK_IF_OWNED, 1, prefix + ":lock", owner)
        raise


async def sync_daily_valid_creator_job(
    ctx, batch_date_text: str, fingerprint: str, owner: str
) -> dict:
    from scripts.daily_valid_creator_pipeline import reconcile
    from scripts.daily_valid_creator_report_gate import missing_creator_reports

    batch_date = date.fromisoformat(batch_date_text)
    batch_prefix = f"valid-creator-sync:{batch_date:%Y%m%d}"
    prefix = f"{batch_prefix}:{fingerprint}"
    redis = ctx["redis"]
    full_read_started = False
    try:
        if batch_date != daily_valid_creator_source_batch(_now(ctx)):
            return {"status": "superseded"}
        if await _batch_sync_succeeded(redis, batch_prefix):
            return {"status": "already_verified"}
        if await redis.get(batch_prefix + ":cooldown") or await redis.get(prefix + ":cooldown"):
            return {"status": "retry_deferred"}
        snapshot = await _ready_snapshot(ctx, _now(ctx))
        if snapshot is None or snapshot[2] != fingerprint:
            raise RuntimeError("Direct TK dates changed or became stale before apply")
        if await missing_creator_reports(ctx["database"], snapshot[0]):
            await _set_cooldown(redis, batch_prefix, prefix,
                                SOURCE_NOT_READY_COOLDOWN_SECONDS)
            return {"status": "source_not_ready"}
        cutoffs, evidence, _ = snapshot
        excluded_accounts = await _excluded_accounts(redis)
        full_read_started = True
        result = await reconcile(
            cutoffs,
            batch_date,
            evidence,
            apply=True,
            excluded_accounts=excluded_accounts,
            refresh_history=True,
            scheduled_update=True,
            backup_directory=os.getenv("DAILY_VALID_CREATOR_BACKUP_DIR",
                                       "/app/runtime/daily-creator-backups"),
            export_url=os.getenv(
                "AFFILIATE_EXPORT_URL",
                "http://127.0.0.1:8080/api/internal/affiliate-center/",
            ),
        )
        await redis.set(prefix + ":success", "1", ex=172800)
        return result["apply"]
    except Exception:
        await _set_cooldown(redis, batch_prefix, prefix, FAILED_SYNC_COOLDOWN_SECONDS
                            if full_read_started else SOURCE_NOT_READY_COOLDOWN_SECONDS)
        raise
    finally:
        await redis.eval(_UNLOCK_IF_OWNED, 1, prefix + ":lock", owner)
