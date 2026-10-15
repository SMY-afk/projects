from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select

from erp_api.infrastructure.database import Database
from erp_api.models.affiliate_creator import AffiliateCreatorReport
from erp_api.models.analytics_sync import AnalyticsSyncRun
from erp_api.services.affiliate_creator_report_completion import (
    AffiliateCreatorReportPartial,
    AffiliatePartialReason,
    apply_creator_report_partial,
)
from erp_api.services.analytics_sync_types import (
    AnalyticsSyncResult,
    partial_summary,
    sync_result,
)


class AnalyticsSyncPartialRepositoryMixin:
    _database: Database

    async def partial_run(
        self,
        tenant_id: UUID,
        run_id: UUID,
        *,
        reason: AffiliatePartialReason,
        creator_report_id: UUID | None = None,
        report_partial: AffiliateCreatorReportPartial | None = None,
    ) -> AnalyticsSyncResult:
        summary = partial_summary(reason)
        async for session in self._database.session(tenant_id):
            run = await session.get(AnalyticsSyncRun, run_id)
            if run is None or run.status != "running":
                raise RuntimeError("Analytics sync run is not active.")
            if run.resource_type == "affiliate_creator":
                if creator_report_id is None or report_partial is None:
                    raise RuntimeError(
                        "Partial creator run requires its report summary."
                    )
                if report_partial.completeness_reason != reason:
                    raise RuntimeError("Creator report partial reason does not match.")
                report = await session.scalar(
                    select(AffiliateCreatorReport).where(
                        AffiliateCreatorReport.id == creator_report_id,
                        AffiliateCreatorReport.tenant_id == tenant_id,
                        AffiliateCreatorReport.shop_id == run.shop_id,
                    )
                )
                apply_creator_report_partial(report, run, report_partial)
            elif creator_report_id is not None or report_partial is not None:
                raise RuntimeError(
                    "Creator report partial is valid only for affiliate creators."
                )
            run.status = "partial"
            run.error_category = reason
            run.error_summary = summary
            run.finished_at = datetime.now(UTC)
            await session.commit()
            return sync_result(run, run.last_source_updated_at)
        raise RuntimeError("Tenant database session was not created.")
