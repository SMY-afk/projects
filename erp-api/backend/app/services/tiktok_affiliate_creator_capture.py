from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from uuid import UUID, uuid4

from backend.app.services.tiktok_affiliate_analytics_context import (
    AffiliateAnalyticsResponseContext,
)
from backend.app.services.tiktok_affiliate_creator_completion import (
    creator_partial_reason,
    creator_report_summary,
)
from backend.app.services.tiktok_affiliate_creator_page import map_creator_page
from backend.app.services.tiktok_affiliate_creator_payload import (
    extract_creator_payload_dimensions,
    validate_shop_timezone,
)
from erp_api.services.affiliate_analytics_commit_service import (
    AffiliateAnalyticsCommitService,
)
from erp_api.services.affiliate_center_contract import (
    AffiliateCenterQuery,
    AffiliateCenterResource,
)
from erp_api.services.affiliate_center_metric_dtos import AffiliateCreatorMetricDTO
from erp_api.services.affiliate_center_read_repository import (
    AffiliateCenterReadRepository,
)
from erp_api.services.affiliate_center_source import AffiliateCenterPageDTO
from erp_api.services.affiliate_creator_persistence import AffiliateCreatorPersistence
from erp_api.services.affiliate_creator_report_completion import (
    AffiliateCreatorReportCompletion,
    AffiliateCreatorReportPartial,
)
from erp_api.services.analytics_sync_repository import AnalyticsSyncRepository


@dataclass(frozen=True)
class AffiliateCreatorCaptureContext:
    platform_shop_id: str
    timezone_offset_hours: str
    query: AffiliateCenterQuery


@dataclass
class _ActiveCreatorRun:
    run_id: UUID
    report_id: UUID
    query_fingerprint: str
    finalized: bool = False


class TikTokAffiliateCreatorCaptureSession:
    def __init__(
        self,
        tenant_id: UUID,
        read_repository: AffiliateCenterReadRepository,
        sync_repository: AnalyticsSyncRepository | None = None,
        persistence: AffiliateCreatorPersistence | None = None,
        *,
        approved_filter_fields: Collection[str] = (),
        expected_query: AffiliateCenterQuery | None = None,
        intent_job_id: str | None = None,
    ) -> None:
        if "shop_id" in approved_filter_fields:
            raise ValueError("shop_id is an identity field, not a creator filter.")
        self._tenant_id = tenant_id
        self._read_repository = read_repository
        self._sync_repository = sync_repository
        self._commit_service = (
            AffiliateAnalyticsCommitService(sync_repository)
            if sync_repository is not None
            else None
        )
        self._persistence = persistence
        self._approved_filter_fields = frozenset(approved_filter_fields)
        self._expected_query: AffiliateCenterQuery | None = None
        self._intent_job_id = intent_job_id
        self._query_fingerprint: str | None = None
        self._active: _ActiveCreatorRun | None = None
        if expected_query is not None:
            self.bind_expected_query(expected_query)

    @property
    def tenant_id(self) -> UUID:
        return self._tenant_id

    def bind_expected_query(self, query: AffiliateCenterQuery) -> None:
        if query.resource is not AffiliateCenterResource.CREATORS:
            raise ValueError("Affiliate creator capture requires a creator query.")
        if self._active is not None or self._query_fingerprint is not None:
            raise RuntimeError("Cannot change the ERP query after capture starts.")
        if self._expected_query and (
            self._expected_query.fingerprint != query.fingerprint
        ):
            raise ValueError("A different ERP query is already bound to this capture.")
        self._expected_query = query

    async def resolve_capture_context(
        self,
        payload: Mapping[str, object],
        response_context: AffiliateAnalyticsResponseContext,
    ) -> AffiliateCreatorCaptureContext:
        dimensions = extract_creator_payload_dimensions(
            payload, self._approved_filter_fields
        )
        platform_shop_id = dimensions.platform_shop_id
        if (
            response_context.platform_shop_id
            and response_context.platform_shop_id != platform_shop_id
        ):
            raise ValueError("Affiliate creator response shop identifier mismatch.")
        shop = await self._read_repository.get_shop_context_by_platform_id(
            self._tenant_id, platform_shop_id
        )
        if shop is None:
            raise ValueError("Affiliate creator response shop is not active in ERP.")
        shop_id = shop.get("shopId")
        shop_timezone = shop.get("shopTimezone")
        if not isinstance(shop_id, UUID) or not isinstance(shop_timezone, str):
            raise TypeError("Affiliate creator shop context is incomplete.")
        validate_shop_timezone(shop_timezone, dimensions)
        currency = dimensions.currency or shop.get("currency")
        if currency is None:
            raise ValueError("Affiliate creator currency is unavailable.")
        if not isinstance(currency, str):
            raise TypeError("Affiliate creator currency must be a string.")
        query = AffiliateCenterQuery(
            resource=AffiliateCenterResource.CREATORS,
            shop_id=shop_id,
            window_start=dimensions.window_start,
            window_end=dimensions.query_window_end(self._expected_query),
            shop_timezone=shop_timezone,
            currency=currency,
            filters=dimensions.filters,
        )
        if (
            self._expected_query is not None
            and self._expected_query.fingerprint != query.fingerprint
        ):
            raise ValueError(
                "Affiliate creator payload query does not match the ERP request."
            )
        self._require_stable_query(query)
        return AffiliateCreatorCaptureContext(
            platform_shop_id=platform_shop_id,
            timezone_offset_hours=dimensions.timezone_offset_text,
            query=query,
        )

    async def build_page(
        self,
        payload: Mapping[str, object],
        observation: Mapping[str, object],
        response_context: AffiliateAnalyticsResponseContext,
        page_number: int,
        next_page_number: int | None,
    ) -> AffiliateCenterPageDTO:
        capture = await self.resolve_capture_context(payload, response_context)
        return map_creator_page(
            capture.query,
            payload,
            observation,
            response_context,
            page_number,
            next_page_number,
        )

    async def persist_page(
        self,
        resource: str,
        payload: Mapping[str, object],
        observation: Mapping[str, object],
        response_context: AffiliateAnalyticsResponseContext,
        page_number: int,
        next_page_number: int | None,
    ) -> None:
        if resource != AffiliateCenterResource.CREATORS.value:
            return
        if self._persistence is None or self._commit_service is None:
            raise RuntimeError("Affiliate creator persistence is not configured.")
        capture = await self.resolve_capture_context(payload, response_context)
        page = map_creator_page(
            capture.query,
            payload,
            observation,
            response_context,
            page_number,
            next_page_number,
        )
        active = await self._active_run(capture)
        await self._commit_page(page, active)

    async def persist_mapped_page(
        self,
        page: AffiliateCenterPageDTO,
        *,
        platform_shop_id: str,
        source_kind: str = "browser_export",
    ) -> None:
        if page.resource is not AffiliateCenterResource.CREATORS:
            raise ValueError("Affiliate creator capture requires creator records.")
        if self._persistence is None or self._commit_service is None:
            raise RuntimeError("Affiliate creator persistence is not configured.")
        if (
            self._expected_query is not None
            and self._expected_query.fingerprint != page.query.fingerprint
        ):
            raise ValueError("Affiliate creator export does not match the ERP request.")
        self._require_stable_query(page.query)
        capture = AffiliateCreatorCaptureContext(
            platform_shop_id=platform_shop_id,
            timezone_offset_hours="",
            query=page.query,
        )
        active = await self._active_run(capture, source_kind=source_kind)
        await self._commit_page(page, active)

    async def refresh_identities(
        self,
        query: AffiliateCenterQuery,
        records: list[AffiliateCreatorMetricDTO],
    ) -> int:
        if self._persistence is None:
            raise RuntimeError("Affiliate creator persistence is not configured.")
        if (
            self._expected_query is not None
            and self._expected_query.fingerprint != query.fingerprint
        ):
            raise ValueError("Affiliate creator identity query does not match.")
        return await self._persistence.refresh_identities(
            self._tenant_id, query.shop_id, records
        )

    async def _commit_page(
        self, page: AffiliateCenterPageDTO, active: _ActiveCreatorRun
    ) -> None:
        async def persist_details(captured_page: AffiliateCenterPageDTO) -> int:
            assert self._persistence is not None
            return await self._persistence.persist_page(
                self._tenant_id, active.report_id, captured_page
            )

        assert self._commit_service is not None
        await self._commit_service.commit_page(
            self._tenant_id,
            active.run_id,
            page,
            persist_details,
        )

    async def finalize_resource(
        self, resource: str, snapshot: Mapping[str, object]
    ) -> None:
        active = self._active
        if (
            resource != AffiliateCenterResource.CREATORS.value
            or active is None
            or active.finalized
        ):
            return
        assert self._commit_service is not None
        summary = creator_report_summary(snapshot)
        if snapshot.get("status") == "complete":
            completion = AffiliateCreatorReportCompletion(
                **summary,
                completeness_reason="complete",
            )
            await self._commit_service.complete_creator_report(
                self._tenant_id,
                active.run_id,
                active.report_id,
                completion,
            )
        else:
            partial = AffiliateCreatorReportPartial(
                **summary,
                completeness_reason=creator_partial_reason(
                    snapshot.get("failure_category")
                ),
            )
            await self._commit_service.mark_creator_partial(
                self._tenant_id,
                active.run_id,
                active.report_id,
                partial,
            )
        active.finalized = True

    async def _active_run(
        self,
        capture: AffiliateCreatorCaptureContext,
        *,
        source_kind: str = "page_capture",
    ) -> _ActiveCreatorRun:
        if self._active is not None:
            if self._active.query_fingerprint != capture.query.fingerprint:
                raise ValueError(
                    "Affiliate creator query changed during a capture run."
                )
            return self._active
        assert self._persistence is not None
        run_id, report_id = await self._persistence.begin_capture(
            self._tenant_id,
            capture.query,
            platform_shop_id=capture.platform_shop_id,
            job_id=(
                self._intent_job_id
                or f"affiliate-page:{capture.query.shop_id}:{uuid4()}"
            ),
            source_kind=source_kind,
        )
        self._active = _ActiveCreatorRun(
            run_id=run_id,
            report_id=report_id,
            query_fingerprint=capture.query.fingerprint,
        )
        return self._active

    def _require_stable_query(self, query: AffiliateCenterQuery) -> None:
        if self._query_fingerprint is None:
            self._query_fingerprint = query.fingerprint
        elif self._query_fingerprint != query.fingerprint:
            raise ValueError("Affiliate creator query changed during a capture run.")
