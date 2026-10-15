from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

from erp_api.services.affiliate_center_contract import (
    AffiliateCenterQuery,
    AffiliateCenterResource,
)
from erp_api.services.affiliate_center_source import (
    AffiliateCenterPageDTO,
    AffiliateMetricDTO,
    AffiliatePaginationDTO,
    AffiliateSourceKind,
    AffiliateSourcePageContext,
)
from erp_api.services.affiliate_creator_metric_parser import (
    parse_creator_official_rows,
    parse_creator_page_payload,
)
from erp_api.services.affiliate_video_metric_parser import (
    parse_video_export_rows,
    parse_video_official_items,
    parse_video_page_payload,
)
from erp_api.services.tiktok_data_schemas import TikTokAnalyticsItem


def map_page_capture(
    query: AffiliateCenterQuery,
    payload: Mapping[str, object],
    *,
    context: AffiliateSourcePageContext,
) -> AffiliateCenterPageDTO:
    records = (
        parse_creator_page_payload(payload, query=query)
        if query.resource is AffiliateCenterResource.CREATORS
        else parse_video_page_payload(payload, query=query)
    )
    pagination = _captured_pagination(query.resource, payload, context)
    return _page("page_capture", query, records, pagination, context, payload)


def map_official_creator_page(
    query: AffiliateCenterQuery,
    rows: Iterable[Mapping[str, object]],
    *,
    context: AffiliateSourcePageContext,
    raw_payload: Mapping[str, object],
) -> AffiliateCenterPageDTO:
    if query.resource is not AffiliateCenterResource.CREATORS:
        raise ValueError("Creator page requires a creators query.")
    records = parse_creator_official_rows(rows, query=query)
    return _page(
        "official_api", query, records, context.pagination(), context, raw_payload
    )


def map_browser_export_creator_page(
    query: AffiliateCenterQuery,
    rows: Iterable[Mapping[str, object]],
    *,
    context: AffiliateSourcePageContext,
    raw_payload: Mapping[str, object],
) -> AffiliateCenterPageDTO:
    if query.resource is not AffiliateCenterResource.CREATORS:
        raise ValueError("Creator export requires a creators query.")
    records = parse_creator_official_rows(rows, query=query)
    return _page(
        "browser_export", query, records, context.pagination(), context, raw_payload
    )


def map_official_video_page(
    query: AffiliateCenterQuery,
    items: Iterable[TikTokAnalyticsItem],
    *,
    context: AffiliateSourcePageContext,
    raw_payload: Mapping[str, object],
) -> AffiliateCenterPageDTO:
    if query.resource is not AffiliateCenterResource.VIDEOS:
        raise ValueError("Video page requires a videos query.")
    records = parse_video_official_items(items, query=query)
    return _page(
        "official_api", query, records, context.pagination(), context, raw_payload
    )


def map_browser_export_video_page(
    query: AffiliateCenterQuery,
    rows: Iterable[Mapping[str, object]],
    *,
    context: AffiliateSourcePageContext,
    raw_payload: Mapping[str, object],
) -> AffiliateCenterPageDTO:
    if query.resource is not AffiliateCenterResource.VIDEOS:
        raise ValueError("Video export requires a videos query.")
    records = parse_video_export_rows(rows, query=query)
    return _page(
        "browser_export", query, records, context.pagination(), context, raw_payload
    )


def _page(
    source_kind: AffiliateSourceKind,
    query: AffiliateCenterQuery,
    records: Sequence[AffiliateMetricDTO],
    pagination: AffiliatePaginationDTO,
    context: AffiliateSourcePageContext,
    raw_payload: Mapping[str, object],
) -> AffiliateCenterPageDTO:
    return AffiliateCenterPageDTO(
        source_kind=source_kind,
        query=query,
        records=tuple(records),
        pagination=pagination,
        request_id=context.request_id,
        source_updated_at=context.source_updated_at,
        raw_payload=dict(raw_payload),
    )


def _captured_pagination(
    resource: AffiliateCenterResource,
    payload: Mapping[str, object],
    context: AffiliateSourcePageContext,
) -> AffiliatePaginationDTO:
    if resource is AffiliateCenterResource.CREATORS:
        observed = _creator_pagination(payload)
        if observed is not None:
            has_more, next_page, total = observed
            return AffiliatePaginationDTO(
                mode=context.pagination_mode,
                page_number=context.page_number or max(1, next_page - 1),
                page_size=context.page_size,
                offset=context.offset,
                next_cursor=(context.next_cursor or f"page:{next_page}")
                if has_more
                else None,
                has_more=has_more,
                total_count=total,
            )
    pagination = context.pagination()
    video_total = _video_total(payload)
    if resource is AffiliateCenterResource.VIDEOS and video_total is not None:
        return AffiliatePaginationDTO(
            mode=pagination.mode,
            page_number=pagination.page_number,
            page_size=pagination.page_size,
            offset=pagination.offset,
            next_cursor=pagination.next_cursor,
            has_more=pagination.has_more,
            total_count=pagination.total_count
            if pagination.total_count is not None
            else video_total,
        )
    return pagination


def _creator_pagination(
    payload: Mapping[str, object],
) -> tuple[bool, int, int | None] | None:
    data = payload.get("data")
    if not isinstance(data, Mapping):
        return None
    segments = data.get("segments")
    if not isinstance(segments, list) or not segments:
        return None
    segment = segments[0]
    if not isinstance(segment, Mapping):
        return None
    control = segment.get("list_control")
    pagination = (
        control.get("next_pagination") if isinstance(control, Mapping) else None
    )
    if not isinstance(pagination, Mapping):
        return None
    has_more, next_page = pagination.get("has_more"), pagination.get("next_page")
    if not isinstance(has_more, bool) or not _integer(next_page):
        return None
    total = pagination.get("total")
    return has_more, next_page, total if _integer(total) else None


def _video_total(payload: Mapping[str, object]) -> int | None:
    data = payload.get("data")
    if not isinstance(data, Mapping):
        return None
    segments = data.get("video_list_segments_v2")
    if not isinstance(segments, list) or not segments:
        return None
    segment = segments[0]
    if not isinstance(segment, Mapping):
        return None
    total = segment.get("total")
    return total if _integer(total) else None


def _integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)
