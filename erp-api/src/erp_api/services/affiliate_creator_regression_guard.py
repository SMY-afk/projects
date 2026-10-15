from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select

from erp_api.models.affiliate_creator import AffiliateCreatorReport
from erp_api.services.affiliate_creator_persistence_rows import capture_lock_key
from erp_api.services.affiliate_creator_report_completion import (
    AffiliateCreatorReportCompletion,
    AffiliateCreatorReportPartial,
    apply_creator_report_partial,
)
from erp_api.services.analytics_sync_types import partial_summary


async def mark_creator_count_regression_partial(
    session,
    tenant_id: UUID,
    run,
    report: AffiliateCreatorReport,
    completion: AffiliateCreatorReportCompletion,
    *,
    completed_at: datetime,
) -> bool:
    """Keep a smaller revision unreadable until its source count is reconciled."""
    await session.execute(
        select(
            func.pg_advisory_xact_lock(
                capture_lock_key(tenant_id, run.shop_id, report.query_fingerprint)
            )
        )
    )
    provider = (getattr(report, "source_metadata", {}) or {}).get("provider")
    previous_query = select(AffiliateCreatorReport).where(
        AffiliateCreatorReport.tenant_id == tenant_id,
        AffiliateCreatorReport.shop_id == run.shop_id,
        AffiliateCreatorReport.query_fingerprint == report.query_fingerprint,
        AffiliateCreatorReport.id != report.id,
        AffiliateCreatorReport.status == "complete",
    )
    if isinstance(provider, str) and provider:
        previous_query = previous_query.where(
            AffiliateCreatorReport.source_metadata["provider"].astext == provider
        )
    previous_report = await session.scalar(
        previous_query
        .order_by(
            AffiliateCreatorReport.revision_no.desc(),
            AffiliateCreatorReport.captured_at.desc(),
        )
        .limit(1)
    )
    if (
        previous_report is None
        or (
            provider
            and (getattr(previous_report, "source_metadata", {}) or {}).get("provider")
            != provider
        )
        or completion.records_unique >= previous_report.records_unique
    ):
        return False
    apply_creator_report_partial(
        report,
        run,
        AffiliateCreatorReportPartial(
            expected_total=previous_report.records_unique,
            pages_fetched=completion.pages_fetched,
            records_received=completion.records_received,
            records_unique=completion.records_unique,
            duplicate_count=completion.duplicate_count,
            completeness_reason="total_count_mismatch",
        ),
    )
    run.status = "partial"
    run.error_category = "total_count_mismatch"
    run.error_summary = partial_summary("total_count_mismatch")
    run.finished_at = completed_at
    return True
