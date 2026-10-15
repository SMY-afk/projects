from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from datetime import timezone as fixed_timezone
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from backend.app.services.tiktok_affiliate_analytics_context import (
    AffiliateAnalyticsResponseContext,
)
from erp_api.services.affiliate_analytics_commit_service import (
    AffiliateAnalyticsCommitService,
)
from erp_api.services.affiliate_center_contract import (
    AffiliateCenterQuery,
    AffiliateCenterResource,
)
from erp_api.services.affiliate_center_read_repository import (
    AffiliateCenterReadRepository,
)
from erp_api.services.affiliate_center_source import (
    AffiliateCenterPageDTO,
    AffiliateSourcePageContext,
)
from erp_api.services.affiliate_center_source_adapters import map_page_capture
from erp_api.services.affiliate_video_persistence import AffiliateVideoPersistence
from erp_api.services.analytics_sync_repository import AnalyticsSyncRepository


@dataclass
class _ActiveVideoRun:
    run_id: UUID
    query_fingerprint: str
    finalized: bool = False


class TikTokAffiliateVideoCaptureSession:
    """Own one bounded page-capture run without retaining browser credentials."""

    def __init__(
        self,
        tenant_id: UUID,
        read_repository: AffiliateCenterReadRepository,
        sync_repository: AnalyticsSyncRepository,
        persistence: AffiliateVideoPersistence,
        *,
        expected_query: AffiliateCenterQuery | None = None,
        intent_job_id: str | None = None,
    ) -> None:
        self._tenant_id = tenant_id
        self._read_repository = read_repository
        self._sync_repository = sync_repository
        self._commit_service = AffiliateAnalyticsCommitService(sync_repository)
        self._persistence = persistence
        self._expected_query = expected_query
        self._intent_job_id = intent_job_id
        self._active: _ActiveVideoRun | None = None

    async def persist_page(
        self,
        resource: str,
        payload: Mapping[str, object],
        observation: Mapping[str, object],
        response_context: AffiliateAnalyticsResponseContext,
        page_number: int,
        next_page_number: int | None,
    ) -> None:
        if resource != AffiliateCenterResource.VIDEOS.value:
            return
        page = await self.build_page(
            payload, observation, response_context, page_number, next_page_number
        )
        await self.persist_mapped_page(page)

    async def build_page(
        self,
        payload: Mapping[str, object],
        observation: Mapping[str, object],
        response_context: AffiliateAnalyticsResponseContext,
        page_number: int,
        next_page_number: int | None,
    ) -> AffiliateCenterPageDTO:
        query = await self._query(payload, response_context)
        mode = _pagination_mode(observation)
        request_id = response_context.request_id
        if not request_id:
            raise ValueError("Affiliate video response request ID is required.")
        context = AffiliateSourcePageContext(
            request_id=request_id,
            pagination_mode=mode,
            page_number=page_number,
            next_cursor=(f"page:{next_page_number}" if next_page_number else None),
            has_more=next_page_number is not None,
        )
        return map_page_capture(query, payload, context=context)

    async def persist_mapped_page(self, page: AffiliateCenterPageDTO) -> None:
        active = await self._active_run(page.query)

        async def persist_details(captured_page) -> int:
            return await self._persistence.persist_page(
                self._tenant_id, active.run_id, captured_page
            )

        await self._commit_service.commit_page(
            self._tenant_id, active.run_id, page, persist_details
        )

    async def finalize_resource(
        self, resource: str, snapshot: Mapping[str, object]
    ) -> None:
        active = self._active
        if (
            resource != AffiliateCenterResource.VIDEOS.value
            or active is None
            or active.finalized
        ):
            return
        if snapshot.get("status") == "complete":
            await self._commit_service.complete_video(
                self._tenant_id,
                active.run_id,
                committed_cursor=None,
            )
            active.finalized = True
            return
        await self._commit_service.mark_video_partial(
            self._tenant_id,
            active.run_id,
            _partial_reason(snapshot.get("failure_category")),
        )
        active.finalized = True

    async def _active_run(self, query: AffiliateCenterQuery) -> _ActiveVideoRun:
        if self._active is not None:
            if self._active.query_fingerprint != query.fingerprint:
                raise ValueError("Affiliate video query changed during a capture run.")
            return self._active
        window_start, window_end = query.utc_window()
        run_id = await self._sync_repository.create_run(
            self._tenant_id,
            query.shop_id,
            resource_type="affiliate_video",
            window_start=window_start,
            window_end=window_end,
            start_cursor=None,
            job_id=(self._intent_job_id or f"affiliate-page:{query.shop_id}:{uuid4()}"),
            currency=query.currency,
            account_type="AFFILIATE_ACCOUNTS",
        )
        await self._sync_repository.start_run(self._tenant_id, run_id)
        self._active = _ActiveVideoRun(run_id, query.fingerprint)
        return self._active

    async def _query(
        self,
        payload: Mapping[str, object],
        response_context: AffiliateAnalyticsResponseContext,
    ) -> AffiliateCenterQuery:
        platform_shop_id = response_context.platform_shop_id
        if not platform_shop_id:
            raise ValueError("Affiliate video response is missing its shop identifier.")
        shop = await self._read_repository.get_shop_context_by_platform_id(
            self._tenant_id, platform_shop_id
        )
        if shop is None:
            raise ValueError("Affiliate video response shop is not active in ERP.")
        timezone = shop.get("shopTimezone")
        shop_id = shop.get("shopId")
        if not isinstance(timezone, str) or not isinstance(shop_id, UUID):
            raise TypeError("Affiliate video shop context is incomplete.")
        window_start, window_end = _payload_window(payload, timezone)
        currency = _payload_currency(payload) or shop.get("currency")
        if currency is None:
            raise ValueError("Affiliate video currency is unavailable.")
        if not isinstance(currency, str):
            raise TypeError("Affiliate video currency must be a string.")
        query = AffiliateCenterQuery(
            resource=AffiliateCenterResource.VIDEOS,
            shop_id=shop_id,
            window_start=window_start,
            window_end=window_end,
            shop_timezone=timezone,
            currency=currency,
            filters={},
        )
        if (
            self._expected_query is not None
            and self._expected_query.fingerprint != query.fingerprint
        ):
            raise ValueError(
                "Affiliate video payload query does not match the ERP request."
            )
        return query


def _payload_window(payload: Mapping[str, object], timezone: str) -> tuple[date, date]:
    descriptor = _first_segment(payload).get("time_descriptor")
    if not isinstance(descriptor, Mapping):
        raise TypeError("Affiliate video response is missing its time descriptor.")
    start = _timestamp(descriptor.get("start_time"), "start_time")
    end = _timestamp(descriptor.get("end_time"), "end_time")
    if end <= start:
        raise ValueError("Affiliate video response has an invalid time window.")
    local_timezone = _payload_timezone(descriptor, timezone)
    start_local = start.astimezone(local_timezone)
    end_local = end.astimezone(local_timezone)
    if end_local.timetz().replace(tzinfo=None) == time.min:
        end_local -= timedelta(microseconds=1)
    return start_local.date(), end_local.date()


def _payload_timezone(descriptor: Mapping[str, object], fallback: str):
    value = descriptor.get("timezone_offset")
    if not isinstance(value, bool) and isinstance(value, (int, float, str)):
        try:
            offset = float(value)
            seconds = offset * 3600 if abs(offset) <= 24 else offset
            if abs(seconds) <= 14 * 3600:
                return fixed_timezone(timedelta(seconds=seconds))
        except (TypeError, ValueError, OverflowError):
            pass
    return ZoneInfo(fallback)


def _payload_currency(payload: Mapping[str, object]) -> str | None:
    performances = _first_segment(payload).get("video_performances")
    if not isinstance(performances, list):
        return None
    for performance in performances:
        if not isinstance(performance, Mapping):
            continue
        metrics = performance.get("video_metrics")
        if not isinstance(metrics, Mapping):
            continue
        for value in metrics.values():
            if isinstance(value, Mapping) and isinstance(
                value.get("currency_code"), str
            ):
                return value["currency_code"]
    return None


def _first_segment(payload: Mapping[str, object]) -> Mapping[str, object]:
    data = payload.get("data")
    segments = data.get("video_list_segments_v2") if isinstance(data, Mapping) else None
    if (
        not isinstance(segments, list)
        or not segments
        or not isinstance(segments[0], Mapping)
    ):
        raise ValueError("Affiliate video response has no video segment.")
    return segments[0]


def _timestamp(value: object, field: str) -> datetime:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise TypeError(f"Affiliate video {field} is invalid.")
    try:
        number = float(value)
        if number > 10_000_000_000:
            number /= 1000
        return datetime.fromtimestamp(number, UTC)
    except (ValueError, OSError, OverflowError) as error:
        raise ValueError(f"Affiliate video {field} is invalid.") from error


def _pagination_mode(observation: Mapping[str, object]):
    pagination = observation.get("pagination")
    mode = pagination.get("mode") if isinstance(pagination, Mapping) else None
    return (
        mode if mode in {"page_page_size", "offset", "cursor", "mixed"} else "unknown"
    )


def _partial_reason(value: object):
    if value in {"total_count_mismatch", "cursor_interrupted"}:
        return value
    return "page_failed"
