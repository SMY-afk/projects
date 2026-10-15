from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select, update

from erp_api.infrastructure.database import Database
from erp_api.models.affiliate_creator import AffiliateCreatorReport
from erp_api.models.analytics_sync import AnalyticsSyncRun
from erp_api.models.shop import Shop
from erp_api.services.affiliate_center_contract import (
    AffiliateCenterQuery,
    AffiliateCenterResource,
)

_RESOURCE_TYPES = {
    AffiliateCenterResource.CREATORS: "affiliate_creator",
    AffiliateCenterResource.VIDEOS: "affiliate_video",
}
_RESOURCE_NAMES = {value: key.value for key, value in _RESOURCE_TYPES.items()}
_ACTIVE_STATUSES = ("queued", "running")
_FAILURE_SUMMARIES = {
    "target_page_missing": "The target TikTok Affiliate Center page is not open.",
    "session_expired": "The TikTok browser session has expired.",
    "captcha": "TikTok requires CAPTCHA verification.",
    "http_403": "TikTok rejected the page request with HTTP 403.",
    "rate_limited": "TikTok rate-limited the page request.",
    "window_not_settable": "The requested page window could not be set safely.",
    "window_not_available": "The requested TikTok data window is not available yet.",
    "window_mismatch": "The captured page window did not match the sync intent.",
    "payload_structure_changed": "The TikTok Affiliate Center payload changed.",
    "creator_probe_structure_changed": "The TikTok creator list probe payload changed.",
    "creator_probe_metadata_failed": "The TikTok creator list probe metadata was unavailable.",
    "creator_probe_context_failed": "The TikTok creator list probe context could not be resolved.",
    "creator_probe_mapping_failed": "The TikTok creator list probe metrics could not be mapped.",
    "creator_probe_request_failed": "The TikTok creator list probe request failed.",
    "creator_export_download_failed": "The TikTok creator export download failed.",
    "creator_export_response_changed": "The TikTok creator export response changed.",
    "creator_export_size_limit": "The TikTok creator export exceeded the safe size limit.",
    "creator_export_parse_changed": "The TikTok creator export columns or values changed.",
    "creator_export_persistence_failed": "The TikTok creator export could not be persisted.",
    "video_export_download_failed": "The TikTok video export download failed.",
    "video_export_request_failed": "The TikTok video export request failed.",
    "video_export_response_changed": "The TikTok video export response changed.",
    "video_export_size_limit": "The TikTok video export exceeded the safe size limit.",
    "video_export_parse_changed": "The TikTok video export columns or values changed.",
    "video_export_persistence_failed": "The TikTok video export could not be persisted.",
    "request_timeout": "The target page did not return a response in time.",
}


@dataclass(frozen=True)
class AffiliateCaptureIntentReceipt:
    run_id: UUID
    resource: str
    resource_type: str
    status: str
    existing: bool


@dataclass(frozen=True)
class AffiliateCaptureIntent:
    run_id: UUID
    job_id: str
    tenant_id: UUID
    shop_id: UUID
    resource: str
    resource_type: str
    platform_shop_id: str
    shop_timezone: str
    currency: str
    window_start: datetime
    window_end: datetime


class AffiliateCaptureIntentRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def enqueue(
        self,
        tenant_id: UUID,
        queries: list[AffiliateCenterQuery],
        *,
        job_id_prefix: str = "affiliate-intent",
        reuse_succeeded: bool = False,
    ) -> list[AffiliateCaptureIntentReceipt]:
        if not job_id_prefix or len(job_id_prefix) > 120:
            raise ValueError("job_id_prefix must contain 1 to 120 characters.")
        receipts: list[AffiliateCaptureIntentReceipt] = []
        async for session in self._database.session(tenant_id):
            for query in queries:
                start, end = query.utc_window()
                resource_type = _RESOURCE_TYPES[query.resource]
                await session.execute(
                    select(
                        func.pg_advisory_xact_lock(_intent_lock_key(tenant_id, query))
                    )
                )
                reusable_statuses = (
                    (*_ACTIVE_STATUSES, "succeeded")
                    if reuse_succeeded
                    else _ACTIVE_STATUSES
                )
                existing = await session.scalar(
                    select(AnalyticsSyncRun)
                    .where(
                        AnalyticsSyncRun.tenant_id == tenant_id,
                        AnalyticsSyncRun.shop_id == query.shop_id,
                        AnalyticsSyncRun.resource_type == resource_type,
                        AnalyticsSyncRun.window_start == start,
                        AnalyticsSyncRun.window_end == end,
                        AnalyticsSyncRun.currency == query.currency,
                        AnalyticsSyncRun.status.in_(reusable_statuses),
                    )
                    .order_by(AnalyticsSyncRun.started_at.desc())
                    .limit(1)
                )
                if existing is not None:
                    receipts.append(_receipt(existing, existing=True))
                    continue
                run = AnalyticsSyncRun(
                    tenant_id=tenant_id,
                    shop_id=query.shop_id,
                    resource_type=resource_type,
                    job_id=f"{job_id_prefix}:{uuid4()}",
                    status="queued",
                    attempt_count=0,
                    window_start=start,
                    window_end=end,
                    currency=query.currency,
                    account_type="AFFILIATE_ACCOUNTS",
                    start_cursor=None,
                    recovery_cursor=None,
                )
                session.add(run)
                await session.flush()
                receipts.append(_receipt(run, existing=False))
            await session.commit()
            return receipts
        raise RuntimeError("Tenant database session was not created.")

    async def next_queued(
        self,
        tenant_id: UUID,
        platform_shop_ids: frozenset[str],
    ) -> AffiliateCaptureIntent | None:
        if not platform_shop_ids:
            return None
        async for session in self._database.session(tenant_id):
            statement = (
                select(AnalyticsSyncRun, Shop.platform_shop_id, Shop.timezone)
                .join(
                    Shop,
                    (Shop.id == AnalyticsSyncRun.shop_id)
                    & (Shop.tenant_id == AnalyticsSyncRun.tenant_id),
                )
                .where(
                    AnalyticsSyncRun.tenant_id == tenant_id,
                    AnalyticsSyncRun.resource_type.in_(_RESOURCE_NAMES),
                    AnalyticsSyncRun.status == "queued",
                    AnalyticsSyncRun.job_id.not_like("official-affiliate%"),
                    Shop.status == "active",
                    Shop.platform_shop_id.in_(platform_shop_ids),
                )
                .order_by(
                    AnalyticsSyncRun.window_start.desc(),
                    AnalyticsSyncRun.started_at.asc(),
                )
                .limit(1)
            )
            row = (await session.execute(statement)).one_or_none()
            if row is None:
                return None
            run, platform_shop_id, timezone = row
            return AffiliateCaptureIntent(
                run_id=run.id,
                job_id=run.job_id,
                tenant_id=tenant_id,
                shop_id=run.shop_id,
                resource=_RESOURCE_NAMES[run.resource_type],
                resource_type=run.resource_type,
                platform_shop_id=platform_shop_id,
                shop_timezone=timezone,
                currency=run.currency,
                window_start=run.window_start,
                window_end=run.window_end,
            )
        raise RuntimeError("Tenant database session was not created.")

    async def fail_intent(self, tenant_id: UUID, run_id: UUID, category: str) -> None:
        if category not in _FAILURE_SUMMARIES:
            raise ValueError("Unsupported affiliate capture intent failure.")
        async for session in self._database.session(tenant_id):
            run = await session.get(AnalyticsSyncRun, run_id)
            if run is None or run.status not in _ACTIVE_STATUSES:
                return
            run.status = "partial" if run.fetched_count else "failed"
            run.error_category = category
            run.error_summary = _FAILURE_SUMMARIES[category]
            run.finished_at = datetime.now(UTC)
            if run.resource_type == "affiliate_creator":
                report = await session.scalar(
                    select(AffiliateCreatorReport).where(
                        AffiliateCreatorReport.tenant_id == tenant_id,
                        AffiliateCreatorReport.shop_id == run.shop_id,
                        or_(
                            AffiliateCreatorReport.source_fingerprint
                            == f"page-capture:{run.id}",
                            AffiliateCreatorReport.source_fingerprint
                            == f"browser-export:{run.id}",
                        ),
                        AffiliateCreatorReport.status == "running",
                    )
                )
                if report is not None:
                    report.status = "partial"
                    report.completeness_reason = "page_failed"
            await session.commit()
            return
        raise RuntimeError("Tenant database session was not created.")

    async def defer_intent(self, tenant_id: UUID, run_id: UUID) -> None:
        async for session in self._database.session(tenant_id):
            run = await session.get(AnalyticsSyncRun, run_id)
            if run is None or run.status not in _ACTIVE_STATUSES:
                return
            run.status = "queued"
            run.error_category = None
            run.error_summary = None
            run.finished_at = None
            run.started_at = datetime.now(UTC)
            await session.commit()
            return
        raise RuntimeError("Tenant database session was not created.")

    async def claim_intent(self, tenant_id: UUID, run_id: UUID) -> bool:
        async for session in self._database.session(tenant_id):
            claimed_id = await session.scalar(
                update(AnalyticsSyncRun)
                .where(
                    AnalyticsSyncRun.id == run_id,
                    AnalyticsSyncRun.tenant_id == tenant_id,
                    AnalyticsSyncRun.status == "queued",
                )
                .values(
                    status="running",
                    attempt_count=AnalyticsSyncRun.attempt_count + 1,
                    started_at=datetime.now(UTC),
                )
                .returning(AnalyticsSyncRun.id)
            )
            await session.commit()
            return claimed_id is not None
        raise RuntimeError("Tenant database session was not created.")


def _receipt(run: AnalyticsSyncRun, *, existing: bool) -> AffiliateCaptureIntentReceipt:
    return AffiliateCaptureIntentReceipt(
        run_id=run.id,
        resource=_RESOURCE_NAMES[run.resource_type],
        resource_type=run.resource_type,
        status=run.status,
        existing=existing,
    )


def _intent_lock_key(tenant_id: UUID, query: AffiliateCenterQuery) -> int:
    identity = f"{tenant_id}:{query.fingerprint}:{query.resource.value}"
    return int.from_bytes(
        sha256(identity.encode("utf-8")).digest()[:8],
        byteorder="big",
        signed=True,
    )
