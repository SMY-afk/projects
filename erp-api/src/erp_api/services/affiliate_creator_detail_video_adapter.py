from __future__ import annotations

from datetime import time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from erp_api.services.affiliate_center_contract import (
    AffiliateCenterQuery,
    AffiliateCenterResource,
)
from erp_api.services.affiliate_center_metric_dtos import AffiliateVideoMetricDTO
from erp_api.services.affiliate_center_source import (
    AffiliateCenterPageDTO,
    AffiliatePaginationDTO,
)
from erp_api.services.affiliate_creator_detail_parser import CreatorDetailPage
from erp_api.services.affiliate_metric_parse_support import timestamp


def creator_detail_video_page(
    page: CreatorDetailPage,
    *,
    shop_id: UUID,
    shop_timezone: str,
    currency: str,
    request_id: str,
    raw_payload: dict[str, object],
) -> AffiliateCenterPageDTO:
    timezone = ZoneInfo(shop_timezone)
    start_local = page.window_start_utc.astimezone(timezone)
    end_local = page.window_end_utc.astimezone(timezone)
    if end_local.timetz().replace(tzinfo=None) == time.min:
        end_local -= timedelta(microseconds=1)
    query = AffiliateCenterQuery(
        resource=AffiliateCenterResource.VIDEOS,
        shop_id=shop_id,
        window_start=start_local.date(),
        window_end=end_local.date(),
        shop_timezone=shop_timezone,
        currency=currency,
        filters={"creatorPageId": page.platform_creator_id},
    )
    records = tuple(
        _video_record(page, record, shop_timezone, currency) for record in page.records
    )
    return AffiliateCenterPageDTO(
        source_kind="page_capture",
        query=query,
        records=records,
        pagination=AffiliatePaginationDTO(
            mode="page_page_size",
            page_number=page.page_number,
            next_cursor=(f"page:{page.next_page}" if page.has_more else None),
            has_more=page.has_more,
            total_count=page.total_count,
        ),
        request_id=request_id,
        source_updated_at=None,
        raw_payload=raw_payload,
    )


def _video_record(page, record, shop_timezone, currency) -> AffiliateVideoMetricDTO:
    identity = record.identity
    metrics = record.metrics
    published = timestamp(identity.get("publishedAt"), "videoPostTime")
    return AffiliateVideoMetricDTO(
        video_id=record.platform_content_id,
        window_start_utc=page.window_start_utc,
        window_end_utc=page.window_end_utc,
        shop_timezone=shop_timezone,
        currency=currency,
        source_identifiers={"tiktok_page_creator_id": page.platform_creator_id},
        creator_username=page.creator_username,
        creator_avatar_url=page.creator_avatar_url,
        title=_optional_text(identity.get("title")),
        video_post_time=published,
        cover_image_url=_optional_text(identity.get("coverImageUrl")),
        gmv_minor=_optional_int(metrics.get("gmvMinor")),
        estimated_commission_minor=_optional_int(
            metrics.get("estimatedCommissionMinor")
        ),
        refunded_gmv_minor=_optional_int(metrics.get("refundedGmvMinor")),
        order_count=_optional_int(metrics.get("orderCount")),
        items_sold=_optional_int(metrics.get("itemsSold")),
        refunded_items=_optional_int(metrics.get("refundedItems")),
        product_impressions=_optional_int(metrics.get("productImpressions")),
        product_clicks=_optional_int(metrics.get("productClicks")),
        views=_optional_int(metrics.get("views")),
        likes=_optional_int(metrics.get("likes")),
        comments=_optional_int(metrics.get("comments")),
        shares=_optional_int(metrics.get("shares")),
        product_click_through_rate=_optional_text(
            metrics.get("productClickThroughRate")
        ),
        extensions=dict(record.extensions),
    )


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _optional_text(value: object) -> str | None:
    return value if isinstance(value, str) else None
