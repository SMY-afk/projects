"""Authenticated complete-batch ingress for local affiliate browser captures."""

from __future__ import annotations

import hashlib
import zlib
from contextlib import asynccontextmanager
from hashlib import blake2b
from secrets import compare_digest
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import ValidationError
from sqlalchemy import func, select

from backend.app.services.tiktok_affiliate_analytics_context import (
    AffiliateAnalyticsResponseContext,
)
from backend.app.services.tiktok_affiliate_creator_capture_factory import (
    build_affiliate_creator_capture,
)
from backend.app.services.tiktok_affiliate_video_capture_factory import (
    build_affiliate_video_capture,
)
from erp_api.models.analytics_sync import AnalyticsSyncRun
from erp_api.services.affiliate_center_contract import (
    AffiliateCenterQuery,
    AffiliateCenterResource,
)
from erp_api.services.affiliate_center_read_repository import (
    AffiliateCenterReadRepository,
)
from erp_api.services.remote_affiliate_capture import (
    RemoteAffiliateBatch,
    validate_mapped_batch,
)

router = APIRouter(prefix="/internal/affiliate-captures", tags=["internal-affiliate"])
MAX_BODY_BYTES = 20 * 1024 * 1024


@router.post("/batches", status_code=202)
async def ingest_affiliate_batch(
    request: Request,
    token: Annotated[str | None, Header(alias="x-erp-affiliate-capture-token")] = None,
):
    settings = request.app.state.settings
    configured = settings.affiliate_capture_service_token
    tenant_id = settings.affiliate_export_tenant_id
    if configured is None or tenant_id is None:
        raise HTTPException(503, "Affiliate capture ingress is not configured")
    if not token or not compare_digest(token, configured.get_secret_value()):
        raise HTTPException(401, headers={"WWW-Authenticate": "ServiceToken"})
    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        raise HTTPException(413, "Affiliate batch exceeds 20 MiB")
    if request.headers.get("content-encoding", "identity").lower() == "gzip":
        try:
            inflater = zlib.decompressobj(16 + zlib.MAX_WBITS)
            body = inflater.decompress(body, MAX_BODY_BYTES + 1)
            if len(body) > MAX_BODY_BYTES or inflater.unconsumed_tail:
                raise HTTPException(413, "Affiliate batch exceeds 20 MiB")
            body += inflater.flush(MAX_BODY_BYTES + 1 - len(body))
            if len(body) > MAX_BODY_BYTES or not inflater.eof:
                raise HTTPException(422, "Affiliate gzip is incomplete")
        except zlib.error as error:
            raise HTTPException(422, "Affiliate gzip is invalid") from error
    elif request.headers.get("content-encoding", "identity").lower() != "identity":
        raise HTTPException(415, "Affiliate encoding is unsupported")
    try:
        batch = RemoteAffiliateBatch.model_validate_json(body)
    except ValidationError as error:
        raise HTTPException(422, "Affiliate batch is invalid") from error
    database = request.app.state.database
    source_hash = hashlib.sha256(body).hexdigest()
    job_id = f"remote-affiliate:{batch.capture_id}:{source_hash}"
    async with _shop_lock(database, tenant_id, batch.shop_id, batch.resource) as locked:
        if not locked:
            raise HTTPException(409, "Affiliate shop capture is busy")
        existing = await _existing_run(database, tenant_id, batch)
        if existing is not None:
            if existing.job_id != job_id:
                raise HTTPException(409, "Capture ID was reused with different content")
            if existing.status == "succeeded":
                return {"status": "stored", "duplicate": True, "run_id": str(existing.id)}
            raise HTTPException(409, "Capture ID already has an incomplete run")
        query = await _expected_query(database, tenant_id, batch)
        session = (
            build_affiliate_creator_capture(
                tenant_id, database, expected_query=query, intent_job_id=job_id
            )
            if batch.resource == "creators"
            else build_affiliate_video_capture(
                tenant_id, database, expected_query=query, intent_job_id=job_id
            )
        )
        try:
            mapped = []
            for page in batch.pages:
                context = AffiliateAnalyticsResponseContext(
                    batch.platform_shop_id, page.request_id
                )
                mapped.append(
                    await session.build_page(
                        page.payload,
                        page.observation,
                        context,
                        page.page_number,
                        page.next_page_number,
                    )
                )
            summary = validate_mapped_batch(batch, mapped)
        except (TypeError, ValueError) as error:
            raise HTTPException(422, "Affiliate batch source evidence is invalid") from error
        try:
            for page in mapped:
                if batch.resource == "creators":
                    await session.persist_mapped_page(
                        page,
                        platform_shop_id=batch.platform_shop_id,
                        source_kind="page_capture",
                    )
                else:
                    await session.persist_mapped_page(page)
            await session.finalize_resource(
                batch.resource, {"status": "complete", **summary}
            )
        except Exception as error:
            await session.finalize_resource(
                batch.resource,
                {"status": "partial", "failure_category": "page_failed", **summary},
            )
            raise HTTPException(503, "Affiliate batch persistence failed") from error
        stored = await _existing_run(database, tenant_id, batch)
        if stored is None or stored.status != "succeeded":
            raise HTTPException(409, "Affiliate completeness guard did not pass")
        return {"status": "stored", "duplicate": False, "run_id": str(stored.id)}


async def _expected_query(database, tenant_id: UUID, batch: RemoteAffiliateBatch):
    shop = await AffiliateCenterReadRepository(database).get_shop_context_by_platform_id(
        tenant_id, batch.platform_shop_id
    )
    if shop is None or shop["shopId"] != batch.shop_id:
        raise HTTPException(409, "Affiliate shop identity is not active in ERP")
    return AffiliateCenterQuery(
        resource=AffiliateCenterResource(batch.resource),
        shop_id=batch.shop_id,
        window_start=batch.window_start,
        window_end=batch.window_end,
        shop_timezone=shop["shopTimezone"],
        currency=shop["currency"],
        filters={},
    )


async def _existing_run(database, tenant_id: UUID, batch: RemoteAffiliateBatch):
    prefix = f"remote-affiliate:{batch.capture_id}:"
    resource = "affiliate_creator" if batch.resource == "creators" else "affiliate_video"
    async for session in database.session(tenant_id):
        return await session.scalar(
            select(AnalyticsSyncRun)
            .where(
                AnalyticsSyncRun.shop_id == batch.shop_id,
                AnalyticsSyncRun.resource_type == resource,
                AnalyticsSyncRun.job_id.like(prefix + "%"),
            )
            .order_by(AnalyticsSyncRun.started_at.desc())
            .limit(1)
        )
    raise RuntimeError("Tenant database session was not created")


@asynccontextmanager
async def _shop_lock(database, tenant_id: UUID, shop_id: UUID, resource: str):
    digest = blake2b(
        b"remote-affiliate\0" + tenant_id.bytes + shop_id.bytes + resource.encode(),
        digest_size=8,
    ).digest()
    key = int.from_bytes(digest, "big", signed=True)
    async with database.engine.begin() as connection:
        yield await connection.scalar(select(func.pg_try_advisory_xact_lock(key))) is True
