from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from erp_api.infrastructure.database import Database
from erp_api.models.affiliate_creator import AffiliateCreator
from erp_api.models.affiliate_creator_detail import (
    AffiliateCreatorDetailItem,
    AffiliateCreatorDetailReport,
)
from erp_api.models.analytics_sync import AnalyticsRawPayload, AnalyticsSyncRun
from erp_api.services.affiliate_avatar_cache_policy import retained_avatar
from erp_api.services.affiliate_center_capture_policy import sanitize_capture_payload
from erp_api.services.affiliate_creator_detail_parser import CreatorDetailPage
from erp_api.services.affiliate_metric_parse_support import creator_username_aliases

DETAIL_UPSERT_BATCH_SIZE = 300


class CreatorDetailRepositoryError(ValueError):
    pass


class AffiliateCreatorDetailRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def start_report(
        self,
        tenant_id: UUID,
        shop_id: UUID,
        page: CreatorDetailPage,
        *,
        shop_timezone: str,
        currency: str,
        filters: dict[str, object],
    ) -> tuple[UUID, UUID]:
        fingerprint = _fingerprint(shop_id, page, shop_timezone, currency, filters)
        async for session in self._database.session(tenant_id):
            creator = await session.scalar(
                select(AffiliateCreator).where(
                    AffiliateCreator.tenant_id == tenant_id,
                    AffiliateCreator.shop_id == shop_id,
                    AffiliateCreator.source_identifiers["tiktok_page_creator_id"].astext
                    == page.platform_creator_id,
                )
            )
            if creator is None and page.creator_username:
                normalized = page.creator_username.strip().lstrip("@").casefold()
                creator = await session.scalar(
                    select(AffiliateCreator).where(
                        AffiliateCreator.tenant_id == tenant_id,
                        AffiliateCreator.shop_id == shop_id,
                        AffiliateCreator.username_normalized.in_(
                            creator_username_aliases(normalized)
                        ),
                    )
                )
            if creator is None:
                raise CreatorDetailRepositoryError(
                    "Creator detail response cannot be matched to an ERP creator."
                )
            identifiers = dict(creator.source_identifiers or {})
            existing = identifiers.get("tiktok_page_creator_id")
            if existing not in {None, page.platform_creator_id}:
                raise CreatorDetailRepositoryError(
                    "Creator page identifier conflicts with existing identity."
                )
            identifiers["tiktok_page_creator_id"] = page.platform_creator_id
            creator.source_identifiers = identifiers
            if page.creator_avatar_url:
                creator.avatar_url = retained_avatar(creator.avatar_url, page.creator_avatar_url)
            running = await session.scalar(
                select(AffiliateCreatorDetailReport)
                .where(
                    AffiliateCreatorDetailReport.tenant_id == tenant_id,
                    AffiliateCreatorDetailReport.shop_id == shop_id,
                    AffiliateCreatorDetailReport.creator_id == creator.id,
                    AffiliateCreatorDetailReport.resource_kind == page.resource_kind,
                    AffiliateCreatorDetailReport.query_fingerprint == fingerprint,
                    AffiliateCreatorDetailReport.status == "running",
                )
                .order_by(AffiliateCreatorDetailReport.captured_at.desc())
                .limit(1)
            )
            if running is not None:
                await session.commit()
                return running.id, running.sync_run_id
            revision = (
                await session.scalar(
                    select(func.max(AffiliateCreatorDetailReport.revision_no)).where(
                        AffiliateCreatorDetailReport.tenant_id == tenant_id,
                        AffiliateCreatorDetailReport.shop_id == shop_id,
                        AffiliateCreatorDetailReport.creator_id == creator.id,
                        AffiliateCreatorDetailReport.resource_kind
                        == page.resource_kind,
                        AffiliateCreatorDetailReport.query_fingerprint == fingerprint,
                    )
                )
                or 0
            ) + 1
            run = AnalyticsSyncRun(
                tenant_id=tenant_id,
                shop_id=shop_id,
                resource_type="affiliate_creator_detail",
                job_id=f"affiliate-creator-detail:{uuid4()}",
                status="running",
                attempt_count=1,
                window_start=page.window_start_utc,
                window_end=page.window_end_utc,
                currency=currency,
                account_type="AFFILIATE_ACCOUNTS",
                start_cursor=f"page:{page.page_number}",
                started_at=datetime.now(UTC),
            )
            session.add(run)
            await session.flush()
            report = AffiliateCreatorDetailReport(
                tenant_id=tenant_id,
                shop_id=shop_id,
                creator_id=creator.id,
                sync_run_id=run.id,
                resource_kind=page.resource_kind,
                query_fingerprint=fingerprint,
                revision_no=revision,
                window_start_utc=page.window_start_utc,
                window_end_utc=page.window_end_utc,
                shop_timezone=shop_timezone,
                currency=currency,
                filters=filters,
                status="running",
                expected_total=page.total_count,
            )
            session.add(report)
            await session.commit()
            return report.id, run.id
        raise RuntimeError("Tenant database session was not created.")

    async def persist_page(
        self,
        tenant_id: UUID,
        report_id: UUID,
        page: CreatorDetailPage,
        *,
        request_id: str,
        raw_payload: dict[str, object],
    ) -> int:
        async for session in self._database.session(tenant_id):
            report = await session.scalar(
                select(AffiliateCreatorDetailReport).where(
                    AffiliateCreatorDetailReport.tenant_id == tenant_id,
                    AffiliateCreatorDetailReport.id == report_id,
                )
            )
            if report is None or report.status != "running":
                raise CreatorDetailRepositoryError(
                    "Creator detail report is not active."
                )
            replayed = await session.scalar(
                select(AnalyticsRawPayload.id).where(
                    AnalyticsRawPayload.tenant_id == tenant_id,
                    AnalyticsRawPayload.sync_run_id == report.sync_run_id,
                    AnalyticsRawPayload.platform_request_id == request_id,
                )
            )
            if replayed is not None:
                return 0
            rows = {
                record.platform_content_id: {
                    "id": uuid4(),
                    "tenant_id": tenant_id,
                    "shop_id": report.shop_id,
                    "report_id": report.id,
                    "platform_content_id": record.platform_content_id,
                    "identity": record.identity,
                    "metrics": record.metrics,
                    "extensions": record.extensions,
                    "source_request_id": request_id,
                }
                for record in page.records
            }
            for batch in _batches(list(rows.values())):
                statement = insert(AffiliateCreatorDetailItem).values(batch)
                statement = statement.on_conflict_do_update(
                    constraint="uq_affiliate_creator_detail_item",
                    set_={
                        "identity": statement.excluded.identity,
                        "metrics": statement.excluded.metrics,
                        "extensions": statement.excluded.extensions,
                        "source_request_id": request_id,
                        "captured_at": func.now(),
                    },
                )
                await session.execute(statement)
            unique_count = await session.scalar(
                select(func.count())
                .select_from(AffiliateCreatorDetailItem)
                .where(
                    AffiliateCreatorDetailItem.tenant_id == tenant_id,
                    AffiliateCreatorDetailItem.report_id == report.id,
                )
            )
            sanitized = sanitize_capture_payload(raw_payload)
            if not isinstance(sanitized, dict):
                raise TypeError("Sanitized creator detail payload must be an object.")
            session.add(
                AnalyticsRawPayload(
                    tenant_id=tenant_id,
                    shop_id=report.shop_id,
                    sync_run_id=report.sync_run_id,
                    payload_kind=f"affiliate_creator_{page.resource_kind}",
                    payload=sanitized,
                    platform_request_id=request_id,
                    expires_at=datetime.now(UTC) + timedelta(days=7),
                )
            )
            report.pages_fetched += 1
            report.records_received += len(page.records)
            report.records_unique = unique_count or 0
            report.expected_total = page.total_count
            run = await session.get(AnalyticsSyncRun, report.sync_run_id)
            if run is None:
                raise CreatorDetailRepositoryError("Creator detail run is missing.")
            run.fetched_count = report.records_received
            run.persisted_count = report.records_unique
            run.recovery_cursor = f"page:{page.next_page}" if page.has_more else None
            run.platform_request_id = request_id
            await session.commit()
            return len(page.records)
        raise RuntimeError("Tenant database session was not created.")

    async def finalize(
        self,
        tenant_id: UUID,
        report_id: UUID,
        *,
        terminal: bool,
        failure_reason: str | None = None,
    ) -> str:
        async for session in self._database.session(tenant_id):
            report = await session.scalar(
                select(AffiliateCreatorDetailReport).where(
                    AffiliateCreatorDetailReport.tenant_id == tenant_id,
                    AffiliateCreatorDetailReport.id == report_id,
                )
            )
            if report is None:
                raise CreatorDetailRepositoryError("Creator detail report is missing.")
            count_matches = (
                report.expected_total is None
                or report.expected_total == report.records_unique
            )
            complete = terminal and count_matches and failure_reason is None
            report.status = "complete" if complete else "partial"
            report.completeness_reason = (
                None if complete else (failure_reason or "total_count_mismatch")
            )
            report.finished_at = datetime.now(UTC)
            run = await session.get(AnalyticsSyncRun, report.sync_run_id)
            if run is None:
                raise CreatorDetailRepositoryError("Creator detail run is missing.")
            run.status = "succeeded" if complete else "partial"
            run.error_category = report.completeness_reason
            run.finished_at = report.finished_at
            if complete:
                run.recovery_cursor = None
            await session.commit()
            return report.status
        raise RuntimeError("Tenant database session was not created.")


def _fingerprint(shop_id, page, timezone, currency, filters) -> str:
    value = {
        "shopId": str(shop_id),
        "creatorId": page.platform_creator_id,
        "resource": page.resource_kind,
        "from": page.window_start_utc.isoformat(),
        "to": page.window_end_utc.isoformat(),
        "timezone": timezone,
        "currency": currency,
        "filters": filters,
    }
    canonical = json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _batches(rows: list[dict[str, object]]):
    for index in range(0, len(rows), DETAIL_UPSERT_BATCH_SIZE):
        yield rows[index : index + DETAIL_UPSERT_BATCH_SIZE]
