from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from sqlalchemy import delete, select

from erp_api.infrastructure.database import Database
from erp_api.models.affiliate_creator import AffiliateCreatorReport
from erp_api.models.analytics_sync import (
    AnalyticsRawPayload,
    AnalyticsSyncCursor,
    AnalyticsSyncRun,
)
from erp_api.services.affiliate_center_capture_policy import (
    AFFILIATE_CENTER_RAW_PAYLOAD_TTL_DAYS,
)
from erp_api.services.affiliate_creator_regression_guard import (
    mark_creator_count_regression_partial,
)
from erp_api.services.affiliate_creator_report_completion import (
    AffiliateCreatorReportCompletion,
    apply_creator_report_completion,
)
from erp_api.services.analytics_resource_types import AnalyticsSyncResourceType
from erp_api.services.analytics_sync_page_replay import (
    AnalyticsSyncPageRepositoryMixin,
)
from erp_api.services.analytics_sync_partial import AnalyticsSyncPartialRepositoryMixin
from erp_api.services.analytics_sync_types import (
    AnalyticsSyncResult,
    StoredAnalyticsCursor,
    failure_summary,
    normalize_sync_window,
    optional_utc,
    sync_result,
)
from erp_api.services.tiktok_data_schemas import AnalyticsErrorCategory


class AnalyticsSyncRepository(
    AnalyticsSyncPageRepositoryMixin, AnalyticsSyncPartialRepositoryMixin
):
    """Records analytics sync progress without committing a cursor before full success."""

    def __init__(self, database: Database, *, raw_payload_ttl_days: int = 30) -> None:
        if raw_payload_ttl_days < 1:
            raise ValueError("raw_payload_ttl_days must be positive.")
        self._database = database
        self._raw_payload_ttl = timedelta(days=raw_payload_ttl_days)

    @classmethod
    def for_affiliate_center(cls, database: Database) -> AnalyticsSyncRepository:
        return cls(
            database,
            raw_payload_ttl_days=AFFILIATE_CENTER_RAW_PAYLOAD_TTL_DAYS,
        )

    async def get_cursor(
        self, tenant_id: UUID, shop_id: UUID, resource_type: AnalyticsSyncResourceType
    ) -> StoredAnalyticsCursor:
        async for session in self._database.session(tenant_id):
            cursor = await session.scalar(
                select(AnalyticsSyncCursor).where(
                    AnalyticsSyncCursor.shop_id == shop_id,
                    AnalyticsSyncCursor.resource_type == resource_type,
                )
            )
            if cursor is None:
                return StoredAnalyticsCursor(None, None, None)
            return StoredAnalyticsCursor(
                cursor.committed_cursor, cursor.last_success_at, cursor.fresh_at
            )
        raise RuntimeError("Tenant database session was not created.")

    async def create_run(
        self,
        tenant_id: UUID,
        shop_id: UUID,
        *,
        resource_type: AnalyticsSyncResourceType,
        window_start: datetime,
        window_end: datetime,
        start_cursor: str | None,
        job_id: str,
        currency: str | None = None,
        account_type: str | None = None,
        reuse_succeeded: bool = False,
    ) -> UUID:
        start, end = normalize_sync_window(window_start, window_end)
        if not job_id or len(job_id) > 160:
            raise ValueError("job_id must contain 1 to 160 characters.")
        async for session in self._database.session(tenant_id):
            reusable_statuses = (
                "queued",
                "running",
                "retry_wait",
                *(("succeeded",) if reuse_succeeded else ()),
            )
            existing_run = await session.scalar(
                select(AnalyticsSyncRun)
                .where(
                    AnalyticsSyncRun.shop_id == shop_id,
                    AnalyticsSyncRun.resource_type == resource_type,
                    AnalyticsSyncRun.job_id == job_id,
                    AnalyticsSyncRun.status.in_(reusable_statuses),
                )
                .order_by(AnalyticsSyncRun.started_at.desc())
                .limit(1)
            )
            if existing_run is not None:
                return existing_run.id
            run = AnalyticsSyncRun(
                tenant_id=tenant_id,
                shop_id=shop_id,
                resource_type=resource_type,
                job_id=job_id,
                status="queued",
                attempt_count=0,
                window_start=start,
                window_end=end,
                currency=currency,
                account_type=account_type,
                start_cursor=start_cursor,
                recovery_cursor=start_cursor,
            )
            session.add(run)
            await session.commit()
            return run.id
        raise RuntimeError("Tenant database session was not created.")

    async def start_run(self, tenant_id: UUID, run_id: UUID) -> None:
        async for session in self._database.session(tenant_id):
            run = await session.get(AnalyticsSyncRun, run_id)
            if run is None:
                raise RuntimeError("Analytics sync run cannot enter running state.")
            if run.status == "running":
                return
            if run.status not in {"queued", "retry_wait"}:
                raise RuntimeError("Analytics sync run cannot enter running state.")
            if run.status == "retry_wait":
                run.recovery_cursor = run.start_cursor
                run.fetched_count = 0
                run.persisted_count = 0
                run.latest_available_date = None
            run.status = "running"
            run.attempt_count += 1
            await session.commit()
            return
        raise RuntimeError("Tenant database session was not created.")

    async def complete_run(
        self,
        tenant_id: UUID,
        run_id: UUID,
        *,
        committed_cursor: str | None = None,
        update_cursor: bool = True,
        creator_report_id: UUID | None = None,
        report_completion: AffiliateCreatorReportCompletion | None = None,
    ) -> AnalyticsSyncResult:
        completed_at = datetime.now(UTC)
        async for session in self._database.session(tenant_id):
            run = await session.get(AnalyticsSyncRun, run_id)
            if run is None or run.status != "running":
                raise RuntimeError("Analytics sync run is not active.")
            if run.resource_type == "affiliate_creator":
                if creator_report_id is None or report_completion is None:
                    raise RuntimeError(
                        "Affiliate creator completion requires its report summary."
                    )
                report = await session.scalar(
                    select(AffiliateCreatorReport).where(
                        AffiliateCreatorReport.id == creator_report_id,
                        AffiliateCreatorReport.tenant_id == tenant_id,
                        AffiliateCreatorReport.shop_id == run.shop_id,
                    )
                )
                if report is None:
                    raise RuntimeError("Affiliate creator report was not found.")
                if await mark_creator_count_regression_partial(
                    session,
                    tenant_id,
                    run,
                    report,
                    report_completion,
                    completed_at=completed_at,
                ):
                    await session.commit()
                    return sync_result(run, run.last_source_updated_at)
                apply_creator_report_completion(report, run, report_completion)
            elif creator_report_id is not None or report_completion is not None:
                raise RuntimeError(
                    "Creator report completion is valid only for affiliate creators."
                )
            fresh_at = run.last_source_updated_at or completed_at
            if update_cursor:
                cursor = await session.scalar(
                    select(AnalyticsSyncCursor).where(
                        AnalyticsSyncCursor.shop_id == run.shop_id,
                        AnalyticsSyncCursor.resource_type == run.resource_type,
                    )
                )
                if cursor is None:
                    cursor = AnalyticsSyncCursor(
                        tenant_id=tenant_id,
                        shop_id=run.shop_id,
                        resource_type=run.resource_type,
                    )
                    session.add(cursor)
                cursor.committed_cursor = (
                    committed_cursor
                    if committed_cursor is not None
                    else run.recovery_cursor
                )
                cursor.last_success_at = completed_at
                cursor.fresh_at = fresh_at
            run.status = "succeeded"
            run.finished_at = completed_at
            await session.commit()
            return sync_result(run, fresh_at)
        raise RuntimeError("Tenant database session was not created.")

    async def fail_run(
        self,
        tenant_id: UUID,
        run_id: UUID,
        *,
        category: AnalyticsErrorCategory,
        status: Literal["retry_wait", "failed", "dead_letter"] = "failed",
    ) -> AnalyticsSyncResult:
        async for session in self._database.session(tenant_id):
            run = await session.get(AnalyticsSyncRun, run_id)
            if run is None or run.status != "running":
                raise RuntimeError("Analytics sync run is not active.")
            run.status = status
            run.error_category = category
            run.error_summary = failure_summary(category)
            run.finished_at = datetime.now(UTC)
            await session.commit()
            return sync_result(run, run.last_source_updated_at)
        raise RuntimeError("Tenant database session was not created.")

    async def cancel_run(self, tenant_id: UUID, run_id: UUID) -> AnalyticsSyncResult:
        async for session in self._database.session(tenant_id):
            run = await session.get(AnalyticsSyncRun, run_id)
            if run is None or run.status not in {"queued", "retry_wait"}:
                raise RuntimeError("Analytics sync run cannot be cancelled.")
            run.status = "cancelled"
            run.finished_at = datetime.now(UTC)
            await session.commit()
            return sync_result(run, run.last_source_updated_at)
        raise RuntimeError("Tenant database session was not created.")

    async def purge_expired_raw_payloads(
        self, tenant_id: UUID, *, now: datetime | None = None
    ) -> int:
        expires_before = optional_utc(now) or datetime.now(UTC)
        async for session in self._database.session(tenant_id):
            result = await session.execute(
                delete(AnalyticsRawPayload).where(
                    AnalyticsRawPayload.expires_at <= expires_before
                )
            )
            await session.commit()
            return result.rowcount or 0
        raise RuntimeError("Tenant database session was not created.")
