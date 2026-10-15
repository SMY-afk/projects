"""Trusted SSH RPC: source read and metadata enrichment only, never business dispatch."""

import asyncio
import json
import re
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert

from erp_api.core.config import get_settings
from erp_api.infrastructure.database import Database
from erp_api.models.sample_application_event import SampleApplicationEvent as Event
from erp_api.services.sample_application_time_enrichment import (
    SampleApplicationTimeEnrichmentService,
)
from erp_api.services.sample_business_readiness import SampleBusinessReadiness
from erp_api.services.sample_shop_sync_lock import SampleShopSyncLock
from scripts.local_sample_metadata_db import (
    SHOP,
    TENANT,
    candidates,
    preview_related,
    verify_applied,
)
from scripts.local_sample_metadata_rules import (
    RECEIPT_EVENT,
    RECEIPT_SOURCE,
    capture_scope,
)
from scripts.local_sample_metadata_state import payload_hash


def require_attempt(request):
    attempt, digest = request.get("attempt_id"), request.get("payload_hash")
    if (not isinstance(attempt, str) or not re.fullmatch("[0-9a-f]{32}", attempt)
            or not isinstance(digest, str) or not re.fullmatch("[0-9a-f]{64}", digest)
            or digest[:32] != attempt):
        raise RuntimeError("metadata_attempt_invalid")
    return attempt, digest


@asynccontextmanager
async def metadata_lock(database, *, wait_seconds=20, clock=None, pause=None):
    """Catch a short normal pipeline gap without pausing collection or holding a busy transaction."""
    clock = clock or asyncio.get_running_loop().time
    pause = pause or asyncio.sleep
    deadline = clock() + wait_seconds
    lock = SampleShopSyncLock(database)
    while True:
        async with lock.acquire(TENANT, SHOP) as acquired:
            if acquired:
                yield True
                return
        remaining = deadline - clock()
        if remaining <= 0:
            yield False
            return
        await pause(min(2, remaining))


async def receipt(database, request):
    attempt, digest = require_attempt(request)
    async with database.system_session_factory() as session:
        await session.execute(text("SET TRANSACTION READ ONLY"))
        event = await session.scalar(select(Event).where(
            Event.tenant_id == TENANT, Event.shop_id == SHOP,
            Event.event_type == RECEIPT_EVENT, Event.event_source == RECEIPT_SOURCE,
            Event.external_event_id == f"metadata:{attempt}",
        ))
    if event is None:
        return {"status": "not_found", "attempt_id": attempt, "payload_hash": digest}
    row = event.after_data
    if (not isinstance(row, dict) or row.get("attempt_id") != attempt
            or row.get("payload_hash") != digest or row.get("status") != "completed"
            or row.get("result") != "metadataApplied"):
        raise RuntimeError("metadata_remote_receipt_invalid")
    return row


async def apply(database, request, activation):
    attempt, digest = require_attempt(request)
    if payload_hash(request["manifest"], request["capture"]) != digest:
        raise RuntimeError("metadata_input_hash_changed")
    async with metadata_lock(database) as acquired:
        if not acquired:
            return no_write(request, "sample_shop_busy")
        existing = await receipt(database, request)
        if existing["status"] == "completed":
            return existing
        try:
            groups, observed = capture_scope(request["manifest"], request["capture"])
            await SampleBusinessReadiness._require_readyz()
            related_ids, anchor_id = await preview_related(database, request["manifest"], groups, activation)
        except Exception as error:  # noqa: BLE001 -- only before enrichment starts
            return no_write(request, safe_reason(error))
        result = await SampleApplicationTimeEnrichmentService(database).enrich(
            tenant_id=TENANT, shop_id=SHOP, applications=groups, observed_at=observed,
            request_id=f"local-metadata:{attempt}",
        )
        if not result.application_ids <= related_ids:
            raise RuntimeError("metadata_enrichment_scope_changed")
        await verify_applied(database, groups, related_ids)
        row = {"status": "completed", "result": "metadataApplied", "attempt_id": attempt,
               "payload_hash": digest, "matched_count": result.matched_count,
               "updated_count": result.updated_count,
               "application_ids": sorted(str(value) for value in result.application_ids),
               "verified_at": datetime.now(UTC).isoformat(),
               "business_dispatch": "original_official_worker"}
        async with database.system_session_factory() as session:
            await session.execute(insert(Event).values(
                tenant_id=TENANT, shop_id=SHOP, sample_application_id=anchor_id,
                event_type=RECEIPT_EVENT, event_source=RECEIPT_SOURCE,
                external_event_id=f"metadata:{attempt}", actor_id="local-metadata-bridge",
                actor_name="Local Metadata Bridge", after_data=row,
                occurred_at=datetime.now(UTC),
            ).on_conflict_do_nothing(constraint="uq_sample_application_events_tenant_shop_source_external"))
            await session.commit()
        return await receipt(database, request)


def no_write(request, reason):
    return {"status": "deferred", "reason": reason, "no_metadata_write": True,
            "attempt_id": request["attempt_id"], "payload_hash": request["payload_hash"]}


def safe_reason(error):
    return str(error) if str(error).startswith(("metadata_", "sample_business_readiness:")) else (
        f"metadata_rpc_{type(error).__name__}")


async def dispatch(request):
    settings = get_settings()
    database = Database(settings.database_url)
    try:
        if request.get("operation") == "status":
            return await receipt(database, request)
        if request.get("operation") == "probe":
            await SampleBusinessReadiness._require_readyz()
            return {"status": "candidates", "manifest": await candidates(
                database, settings.feishu_sample_auto_assignment_activation_at)}
        if request.get("operation") == "apply":
            return await apply(database, request, settings.feishu_sample_auto_assignment_activation_at)
        raise RuntimeError("metadata_rpc_operation_invalid")
    except Exception as error:  # noqa: BLE001 -- bounded trusted RPC; do not log source payloads
        return {"status": "blocked", "reason": safe_reason(error)}
    finally:
        await database.dispose()


def main(request):
    print(json.dumps(asyncio.run(dispatch(request)), ensure_ascii=False), flush=True)
