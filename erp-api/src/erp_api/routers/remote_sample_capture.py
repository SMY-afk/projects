"""Authenticated local collector ingress; no browser or Feishu work in HTTP."""

from __future__ import annotations

import hashlib
import zlib
from datetime import datetime
from secrets import compare_digest
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request, status
from pydantic import ValidationError
from sqlalchemy import func, select

from erp_api.models.sample_application import SampleApplication
from erp_api.models.sample_ingest_batch import SampleIngestBatch
from erp_api.services.hubstudio_sample_application_source import HubStudioSampleTarget
from erp_api.services.hubstudio_sample_ingest_service import (
    HubStudioSampleIngestService,
)
from erp_api.services.hubstudio_sample_types import HubStudioSampleCapture
from erp_api.services.remote_sample_capture import (
    RemoteSampleBatch,
    parse_complete_batch,
)
from erp_api.services.sample_application_repository import SampleApplicationRepository
from erp_api.services.sample_shop_sync_lock import SampleShopSyncLock
from erp_api.services.sample_source_policy import (
    SampleSourcePolicy,
    SampleSourcePolicyError,
    SampleSourcePolicyRepository,
)
from erp_api.services.sample_sync_audit_repository import SampleSyncAuditRepository
from erp_api.services.tiktok_transport import TikTokApiError
from erp_api.workers.sample_queue import SAMPLE_QUEUE_NAME

router = APIRouter(prefix="/internal/sample-captures", tags=["internal-samples"])
MAX_BODY_BYTES = 20 * 1024 * 1024


@router.post("/batches", status_code=status.HTTP_202_ACCEPTED)
async def ingest_remote_batch(
    request: Request,
    token: Annotated[str | None, Header(alias="x-erp-capture-token")] = None,
    process: Annotated[str | None, Header(alias="x-erp-capture-process")] = None,
):
    settings = request.app.state.settings
    configured = settings.sample_capture_service_token
    tenant_id = settings.affiliate_export_tenant_id
    if configured is None or tenant_id is None:
        raise HTTPException(503, "Sample capture ingress is not configured")
    if not token or not compare_digest(token, configured.get_secret_value()):
        raise HTTPException(401, headers={"WWW-Authenticate": "ServiceToken"})
    if process not in (None, "defer", "enqueue"):
        raise HTTPException(422, "Sample processing mode is invalid")
    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        raise HTTPException(413, "RAW sample batch exceeds 20 MiB")
    encoding = request.headers.get("content-encoding", "identity").lower()
    if encoding == "gzip":
        try:
            inflater = zlib.decompressobj(16 + zlib.MAX_WBITS)
            body = inflater.decompress(body, MAX_BODY_BYTES + 1)
            if len(body) > MAX_BODY_BYTES or inflater.unconsumed_tail:
                raise HTTPException(413, "RAW sample batch exceeds 20 MiB")
            body += inflater.flush(MAX_BODY_BYTES + 1 - len(body))
            if len(body) > MAX_BODY_BYTES:
                raise HTTPException(413, "RAW sample batch exceeds 20 MiB")
            if not inflater.eof:
                raise HTTPException(422, "RAW sample gzip is incomplete")
        except zlib.error as error:
            raise HTTPException(422, "RAW sample gzip is invalid") from error
    elif encoding != "identity":
        raise HTTPException(415, "RAW sample encoding is unsupported")
    try:
        batch = RemoteSampleBatch.model_validate_json(body)
        pages, payload_hash = parse_complete_batch(batch)
    except (ValidationError, ValueError, TypeError, TikTokApiError) as error:
        raise HTTPException(422, "RAW sample batch is invalid") from error
    database = request.app.state.database
    if batch.sample_type == "refundable" and not (
        getattr(settings, "feishu_refundable_sample_enabled", False)
        and getattr(settings, "feishu_refundable_assignment_record_table_id", None)
    ):
        raise HTTPException(409, "Refundable sample processing is not enabled")
    source_payload_hash = hashlib.sha256(
        batch.model_dump_json(
            exclude={"sample_type"} if batch.sample_type == "free" else None
        ).encode("utf-8")
    ).hexdigest()
    async with SampleShopSyncLock(database).acquire(tenant_id, batch.shop_id) as locked:
        if not locked:
            raise HTTPException(409, "Shop sample sync is busy", headers={"x-erp-capture-error": "busy"})
        existing = await _completed_batch(database, tenant_id, batch)
        if existing is not None:
            evidence = existing.completeness_evidence or {}
            if (
                existing.payload_hash != payload_hash
                or existing.page_count != len(pages)
                or evidence.get("source_payload_hash") != source_payload_hash
                or evidence.get("environment_id") != batch.environment_id
                or evidence.get("platform_shop_id") != batch.platform_shop_id
            ):
                raise HTTPException(409, "Capture ID was reused with different content", headers={"x-erp-capture-error": "capture_conflict"})
            batch_id = existing.id
            duplicate = True
        else:
            policy = SampleSourcePolicy(SampleSourcePolicyRepository(database))
            try:
                await policy.require_hubstudio_fallback(
                    tenant_id=tenant_id,
                    shop_id=batch.shop_id,
                    platform_shop_id=batch.platform_shop_id,
                    official_access_state="missing_scope",
                    sample_type=batch.sample_type,
                )
            except SampleSourcePolicyError as error:
                raise HTTPException(409, error.code) from error
            latest_observation = await _latest_observation(
                database, tenant_id, batch.shop_id, sample_type=batch.sample_type
            )
            if (
                latest_observation is not None
                and min(page.observed_at for page in batch.pages) < latest_observation
            ):
                raise HTTPException(409, "RAW sample batch is older than stored source", headers={"x-erp-capture-error": "stale_capture"})
            target = HubStudioSampleTarget(
                tenant_id=tenant_id,
                shop_id=batch.shop_id,
                environment_id=batch.environment_id,
                platform_shop_id=batch.platform_shop_id,
                cdp_url="http://127.0.0.1:1",
                official_access_state="missing_scope",
            )
            ingest = HubStudioSampleIngestService(
                SampleSyncAuditRepository(database),
                SampleApplicationRepository(database),
                source_identity=f"remote:{batch.capture_id}",
                source_payload_hash=source_payload_hash,
                sample_type=batch.sample_type,
            )
            result = None
            for item, page in zip(batch.pages, pages, strict=True):
                result = await ingest.ingest_page(
                    HubStudioSampleCapture(target, page, item.observed_at)
                )
            if result is None or result.status != "succeeded":
                raise HTTPException(409, "RAW sample ingest did not complete")
            batch_id = result.batch_id
            duplicate = False
    if process == "enqueue":
        queue = getattr(request.app.state, "arq_queue", None)
        if queue is None:
            raise HTTPException(503, "Sample worker queue is unavailable")
        try:
            await queue.enqueue_job(
                "process_remote_sample_batch_job",
                str(tenant_id),
                str(batch.shop_id),
                str(batch_id),
                _queue_name=SAMPLE_QUEUE_NAME,
                _job_id=f"remote-sample:{batch_id}",
            )
        except Exception as error:
            raise HTTPException(503, "Sample worker queue is unavailable") from error
    return {
        "batch_id": str(batch_id),
        "status": "stored",
        "duplicate": duplicate,
        "processing": "queued" if process == "enqueue" else "deferred",
    }


async def _completed_batch(database, tenant_id: UUID, batch: RemoteSampleBatch):
    async with database.system_session_factory() as session:
        return await session.scalar(
            select(SampleIngestBatch)
            .where(
                SampleIngestBatch.tenant_id == tenant_id,
                SampleIngestBatch.shop_id == batch.shop_id,
                SampleIngestBatch.source_type == "hubstudio_cdp",
                SampleIngestBatch.source_identity == f"remote:{batch.capture_id}",
                SampleIngestBatch.status == "complete",
            )
            .order_by(SampleIngestBatch.started_at.desc())
            .limit(1)
        )


async def _latest_observation(
    database, tenant_id: UUID, shop_id: UUID, *, sample_type: str = "free"
) -> datetime | None:
    async with database.system_session_factory() as session:
        return await session.scalar(
            select(func.max(SampleApplication.source_observed_at)).where(
                SampleApplication.tenant_id == tenant_id,
                SampleApplication.shop_id == shop_id,
                SampleApplication.sample_type == sample_type,
            )
        )
