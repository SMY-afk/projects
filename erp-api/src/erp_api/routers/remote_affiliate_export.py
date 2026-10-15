"""Authenticated original-XLSX ingress; no Feishu or local database writes."""

from __future__ import annotations

import hashlib
from contextlib import asynccontextmanager
from hashlib import blake2b
from secrets import compare_digest
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import ValidationError
from sqlalchemy import func, select

from backend.app.services.tiktok_affiliate_creator_capture_factory import (
    build_affiliate_creator_capture,
)
from backend.app.services.tiktok_affiliate_video_capture_factory import (
    build_affiliate_video_capture,
)
from erp_api.models.analytics_sync import AnalyticsSyncRun
from erp_api.models.shop import Shop
from erp_api.services.affiliate_capture_health import AffiliateCaptureHealthRepository
from erp_api.services.affiliate_center_contract import (
    AffiliateCenterQuery,
    AffiliateCenterResource,
)
from erp_api.services.affiliate_center_read_repository import (
    AffiliateCenterReadRepository,
)
from erp_api.services.affiliate_local_export_service import TARGET_SHOPS
from erp_api.services.remote_affiliate_export import (
    MAX_EXPORT_BYTES,
    RemoteAffiliateExportManifest,
    map_validated_export,
)
from erp_api.services.remote_affiliate_health import RemoteAffiliateHealthReport

router = APIRouter(prefix="/internal/affiliate-exports", tags=["internal-affiliate"])


@router.post("/health", status_code=202)
async def record_remote_capture_health(
    request: Request,
    token: Annotated[str | None, Header(alias="x-erp-affiliate-capture-token")] = None,
):
    settings = request.app.state.settings
    configured = settings.affiliate_capture_service_token
    tenant_id = settings.affiliate_export_tenant_id
    if configured is None or tenant_id is None:
        raise HTTPException(503, "Affiliate health ingress is not configured")
    if not token or not compare_digest(token, configured.get_secret_value()):
        raise HTTPException(401, headers={"WWW-Authenticate": "ServiceToken"})
    body = await request.body()
    if len(body) > 4096:
        raise HTTPException(413, "Affiliate health report is too large")
    try:
        report = RemoteAffiliateHealthReport.model_validate_json(body)
        report.validate_freshness(datetime.now(UTC))
    except (ValidationError, ValueError) as error:
        raise HTTPException(422, "Affiliate health report is invalid") from error
    database = request.app.state.database
    async with database.system_session_factory() as session:
        shop_id = await session.scalar(
            select(Shop.id).where(
                Shop.tenant_id == tenant_id,
                Shop.id == report.shop_id,
                Shop.platform == "tiktok",
                Shop.platform_shop_id == report.platform_shop_id,
                Shop.shop_name.in_(item.source_name for item in TARGET_SHOPS),
                Shop.status == "active",
            )
        )
    if shop_id != report.shop_id:
        raise HTTPException(409, "Affiliate shop identity is not active in ERP")
    redis = getattr(request.app.state, "arq_queue", None)
    if redis is None:
        raise HTTPException(503, "Affiliate health storage is unavailable")
    repository = AffiliateCaptureHealthRepository(redis)
    fresh_dates = []
    for item in report.dates:
        previous = await repository.observed_evidence_for(
            tenant_id, report.shop_id, item.resource
        )
        if previous is not None:
            if item.latest_available_date < previous[0] or (
                item.latest_available_date > previous[0]
                and item.observed_at <= previous[1]
            ):
                raise HTTPException(409, "Affiliate date observation regressed")
            if item.observed_at <= previous[1]:
                continue
        fresh_dates.append(item)
    try:
        for item in fresh_dates:
            await repository.record_observation(
                tenant_id,
                report.shop_id,
                item.resource,
                item.latest_available_date,
                now=item.observed_at,
            )
        await repository.record(tenant_id, report.shop_id, report.state)
    except ValueError as error:
        raise HTTPException(409, "Affiliate date observation regressed") from error
    return {"status": "stored", "state": report.state}


@router.post("/workbooks", status_code=202)
async def ingest_export_workbook(
    request: Request,
    token: Annotated[str | None, Header(alias="x-erp-affiliate-capture-token")] = None,
    manifest_json: Annotated[str | None, Header(alias="x-erp-export-manifest")] = None,
):
    settings = request.app.state.settings
    configured = settings.affiliate_capture_service_token
    tenant_id = settings.affiliate_export_tenant_id
    if configured is None or tenant_id is None:
        raise HTTPException(503, "Affiliate export ingress is not configured")
    if not token or not compare_digest(token, configured.get_secret_value()):
        raise HTTPException(401, headers={"WWW-Authenticate": "ServiceToken"})
    if not manifest_json or len(manifest_json) > 2048:
        raise HTTPException(422, "Affiliate export manifest is missing")
    try:
        manifest = RemoteAffiliateExportManifest.model_validate_json(manifest_json)
    except ValidationError as error:
        raise HTTPException(422, "Affiliate export manifest is invalid") from error
    content = await request.body()
    if len(content) > MAX_EXPORT_BYTES:
        raise HTTPException(413, "Affiliate export exceeds 25 MiB")
    database = request.app.state.database
    job_digest = hashlib.sha256(manifest_json.encode() + content).hexdigest()
    job_id = f"remote-export:{manifest.capture_id}:{job_digest}"
    async with _shop_lock(database, tenant_id, manifest.shop_id, manifest.resource) as locked:
        if not locked:
            raise HTTPException(409, "Affiliate shop export is busy")
        existing = await _existing_run(database, tenant_id, manifest)
        if existing is not None:
            if existing.job_id != job_id:
                raise HTTPException(409, "Export capture ID was reused")
            if existing.status == "succeeded":
                return {"status": "stored", "duplicate": True, "run_id": str(existing.id)}
            raise HTTPException(409, "Export capture already has an incomplete run")
        query = await _expected_query(database, tenant_id, manifest)
        try:
            page, summary = map_validated_export(manifest, content, query)
        except (TypeError, ValueError) as error:
            raise HTTPException(422, "Affiliate XLSX or source total is invalid") from error
        capture = (
            build_affiliate_creator_capture(
                tenant_id, database, expected_query=query, intent_job_id=job_id
            )
            if manifest.resource == "creators"
            else build_affiliate_video_capture(
                tenant_id, database, expected_query=query, intent_job_id=job_id
            )
        )
        try:
            if manifest.resource == "creators":
                await capture.persist_mapped_page(
                    page, platform_shop_id=manifest.platform_shop_id
                )
            else:
                await capture.persist_mapped_page(page)
        except Exception as error:
            await capture.finalize_resource(
                manifest.resource,
                {"status": "partial", "failure_category": "page_failed", **summary},
            )
            raise HTTPException(503, "Affiliate export persistence failed") from error
        await capture.finalize_resource(
            manifest.resource, {"status": "complete", **summary}
        )
        stored = await _existing_run(database, tenant_id, manifest)
        if stored is None or stored.status != "succeeded":
            raise HTTPException(409, "Affiliate completeness guard did not pass")
        return {"status": "stored", "duplicate": False, "run_id": str(stored.id)}


async def _expected_query(database, tenant_id: UUID, manifest):
    shop = await AffiliateCenterReadRepository(database).get_shop_context_by_platform_id(
        tenant_id, manifest.platform_shop_id
    )
    if shop is None or shop["shopId"] != manifest.shop_id:
        raise HTTPException(409, "Affiliate shop identity is not active in ERP")
    return AffiliateCenterQuery(
        resource=AffiliateCenterResource(manifest.resource),
        shop_id=manifest.shop_id,
        window_start=manifest.window_start,
        window_end=manifest.window_end,
        shop_timezone=shop["shopTimezone"],
        currency=shop["currency"],
        filters={},
    )


async def _existing_run(database, tenant_id: UUID, manifest):
    prefix = f"remote-export:{manifest.capture_id}:"
    resource = (
        "affiliate_creator" if manifest.resource == "creators" else "affiliate_video"
    )
    async for session in database.session(tenant_id):
        return await session.scalar(
            select(AnalyticsSyncRun)
            .where(
                AnalyticsSyncRun.shop_id == manifest.shop_id,
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
        b"remote-affiliate-export\0"
        + tenant_id.bytes
        + shop_id.bytes
        + resource.encode(),
        digest_size=8,
    ).digest()
    key = int.from_bytes(digest, "big", signed=True)
    async with database.engine.begin() as connection:
        yield await connection.scalar(select(func.pg_try_advisory_xact_lock(key))) is True
