from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from uuid import UUID

from app.parsers.affiliate_creator_export_parser import parse_affiliate_creator_export
from erp_api.services.affiliate_analytics_commit_service import (
    AffiliateAnalyticsCommitService,
)
from erp_api.services.affiliate_center_contract import AffiliateCenterQuery
from erp_api.services.affiliate_center_source import AffiliateSourcePageContext
from erp_api.services.affiliate_center_source_adapters import (
    map_browser_export_creator_page,
)
from erp_api.services.affiliate_creator_report_completion import (
    AffiliateCreatorReportCompletion,
    AffiliateCreatorReportPartial,
)
from erp_api.services.affiliate_official_creator_validation import (
    validate_official_creator_export,
)
from erp_api.services.tiktok_compass_client import CompassExport


@dataclass(frozen=True)
class CreatorFileIngestResult:
    run_id: UUID
    report_id: UUID
    status: str
    record_count: int
    source_row_count: int
    unidentified_row_count: int
    affiliate_gmv_minor: int
    estimated_commission_minor: int
    order_count: int
    items_sold: int


class AffiliateCreatorFileIngestService:
    """Validate and persist one official Seller Center XLSX snapshot."""

    def __init__(self, sync_repository, persistence) -> None:
        self._commit = AffiliateAnalyticsCommitService(sync_repository)
        self._persistence = persistence

    async def ingest(
        self,
        tenant_id: UUID,
        query: AffiliateCenterQuery,
        *,
        platform_shop_id: str,
        job_id: str,
        file_name: str,
        content: bytes,
        source_row_count: int | None = None,
    ) -> CreatorFileIngestResult:
        rows = parse_affiliate_creator_export(content, query.currency)
        export = CompassExport(job_id, file_name, content)
        audit = validate_official_creator_export(
            export,
            window_start=query.window_start,
            window_end=query.window_end,
            rows=rows,
        )
        source_total = source_row_count or audit.record_count
        if source_total < audit.record_count:
            raise ValueError("Source row count cannot be below parsed records.")
        missing = source_total - audit.record_count
        fingerprint = sha256(content).hexdigest()
        run_id, report_id = await self._persistence.begin_capture(
            tenant_id,
            query,
            platform_shop_id=platform_shop_id,
            job_id=job_id,
            source_kind="browser_export",
            source_metadata={
                "provider": "tiktok_compass_creator_xlsx_seller_center",
                "fileName": file_name,
                "fileSha256": fingerprint,
                "sourceRowCount": source_total,
                "unidentifiedRowCount": missing,
            },
        )
        try:
            page = map_browser_export_creator_page(
                query,
                rows,
                context=AffiliateSourcePageContext(
                    request_id="seller-center:" + fingerprint[:32],
                    pagination_mode="unknown",
                    page_number=1,
                    page_size=max(1, audit.record_count),
                    has_more=False,
                    total_count=audit.record_count,
                    source_updated_at=datetime.now(UTC),
                ),
                raw_payload={
                    "source": "tiktok_compass_creator_xlsx_seller_center",
                    "format": "xlsx",
                    "recordCount": audit.record_count,
                    "sourceRowCount": source_total,
                    "unidentifiedRowCount": missing,
                    "fileSha256": fingerprint,
                    "affiliateGmvMinor": audit.gmv_minor,
                    "estimatedCommissionMinor": audit.commission_minor,
                    "affiliateOrderCount": audit.order_count,
                    "itemsSold": sum(int(row.get("itemsSold") or 0) for row in rows),
                },
            )
            persisted = await self._commit.commit_page(
                tenant_id,
                run_id,
                page,
                lambda item: self._persistence.persist_page(
                    tenant_id, report_id, item
                ),
            )
            if len(page.records) != audit.record_count or persisted not in {
                0,
                audit.record_count,
            }:
                raise RuntimeError("Validated Creator XLSX was not fully persisted.")
            sync_result = await self._commit.complete_creator_report(
                tenant_id,
                run_id,
                report_id,
                AffiliateCreatorReportCompletion(
                    expected_total=audit.record_count,
                    pages_fetched=1,
                    records_received=source_total,
                    records_unique=audit.record_count,
                    duplicate_count=0,
                    completeness_reason="complete",
                ),
            )
        except Exception:
            await self._commit.mark_creator_partial(
                tenant_id,
                run_id,
                report_id,
                AffiliateCreatorReportPartial(
                    expected_total=source_total,
                    pages_fetched=0,
                    records_received=0,
                    records_unique=0,
                    duplicate_count=0,
                    completeness_reason="page_failed",
                ),
            )
            raise
        return CreatorFileIngestResult(
            run_id=run_id,
            report_id=report_id,
            status=sync_result.status,
            record_count=audit.record_count,
            source_row_count=source_total,
            unidentified_row_count=missing,
            affiliate_gmv_minor=audit.gmv_minor,
            estimated_commission_minor=audit.commission_minor,
            order_count=audit.order_count,
            items_sold=sum(int(row.get("itemsSold") or 0) for row in rows),
        )
