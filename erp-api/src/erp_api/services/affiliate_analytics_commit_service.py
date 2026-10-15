from __future__ import annotations

from collections.abc import Awaitable, Callable
from uuid import UUID

from erp_api.services.affiliate_center_source import AffiliateCenterPageDTO
from erp_api.services.affiliate_creator_report_completion import (
    AffiliateCreatorReportCompletion,
    AffiliateCreatorReportPartial,
    AffiliatePartialReason,
)
from erp_api.services.analytics_sync_repository import (
    AnalyticsSyncRepository,
)
from erp_api.services.analytics_sync_types import AnalyticsSyncResult

PersistPageDetails = Callable[[AffiliateCenterPageDTO], Awaitable[int]]


class AffiliateAnalyticsCommitService:
    """Orders durable detail writes before raw-page and cursor audit commits."""

    def __init__(self, sync_repository: AnalyticsSyncRepository) -> None:
        self._sync_repository = sync_repository

    async def commit_page(
        self,
        tenant_id: UUID,
        run_id: UUID,
        page: AffiliateCenterPageDTO,
        persist_details: PersistPageDetails,
    ) -> int:
        if await self._sync_repository.has_recorded_page(
            tenant_id,
            page.query.shop_id,
            run_id,
            platform_request_id=page.request_id,
            raw_payload_kind=page.raw_payload_kind,
            page_number=page.pagination.page_number,
        ):
            return 0
        persisted_count = await persist_details(page)
        await self._sync_repository.record_page(
            tenant_id,
            run_id,
            next_cursor=page.pagination.next_cursor,
            fetched_count=len(page.records),
            persisted_count=persisted_count,
            platform_request_id=page.request_id,
            source_updated_at=page.source_updated_at,
            raw_payload_kind=page.raw_payload_kind,
            raw_payload=page.raw_payload,
            page_number=page.pagination.page_number,
        )
        return persisted_count

    async def complete_creator_report(
        self,
        tenant_id: UUID,
        run_id: UUID,
        report_id: UUID,
        completion: AffiliateCreatorReportCompletion,
    ) -> AnalyticsSyncResult:
        return await self._sync_repository.complete_run(
            tenant_id,
            run_id,
            committed_cursor=None,
            creator_report_id=report_id,
            report_completion=completion,
        )

    async def complete_video(
        self,
        tenant_id: UUID,
        run_id: UUID,
        *,
        committed_cursor: str | None,
    ) -> AnalyticsSyncResult:
        return await self._sync_repository.complete_run(
            tenant_id,
            run_id,
            committed_cursor=committed_cursor,
        )

    async def mark_creator_partial(
        self,
        tenant_id: UUID,
        run_id: UUID,
        report_id: UUID,
        partial: AffiliateCreatorReportPartial,
    ) -> AnalyticsSyncResult:
        return await self._sync_repository.partial_run(
            tenant_id,
            run_id,
            reason=partial.completeness_reason,
            creator_report_id=report_id,
            report_partial=partial,
        )

    async def mark_video_partial(
        self,
        tenant_id: UUID,
        run_id: UUID,
        reason: AffiliatePartialReason,
    ) -> AnalyticsSyncResult:
        return await self._sync_repository.partial_run(
            tenant_id,
            run_id,
            reason=reason,
        )
