from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from erp_api.services.affiliate_center_contract import AffiliateCenterResource
from erp_api.services.affiliate_center_metric_dtos import (
    AffiliateVideoMetricDTO,
    AffiliateVideoProductDTO,
)
from erp_api.services.affiliate_center_source import AffiliateCenterPageDTO
from erp_api.services.affiliate_video_cover_storage import AffiliateVideoCoverStorage
from erp_api.services.analytics_repository import AnalyticsRepository
from erp_api.services.tiktok_data_schemas import TikTokAnalyticsItem
from erp_api.services.video_performance_repository import VideoPerformanceRepository

logger = logging.getLogger(__name__)


class AffiliateVideoPersistence:
    """Persist the shared Affiliate video DTO into content and windowed facts."""

    def __init__(
        self,
        content_repository: AnalyticsRepository,
        performance_repository: VideoPerformanceRepository,
        *,
        cover_storage: AffiliateVideoCoverStorage | None = None,
    ) -> None:
        self._content_repository = content_repository
        self._performance_repository = performance_repository
        self._cover_storage = cover_storage

    async def persist_page(
        self,
        tenant_id: UUID,
        run_id: UUID,
        page: AffiliateCenterPageDTO,
    ) -> int:
        if page.resource is not AffiliateCenterResource.VIDEOS:
            raise ValueError("Affiliate video persistence requires a video resource.")
        records = list(page.records)
        if any(not isinstance(record, AffiliateVideoMetricDTO) for record in records):
            raise TypeError("Affiliate video page contains a non-video DTO.")
        cover_keys = await self._store_covers(tenant_id, page.query.shop_id, records)
        content_items = [
            _content_item(record, cover_keys.get(record.video_id)) for record in records
        ]
        performance_items = [_performance_item(record) for record in records]
        content_options = (
            {"preserve_existing_details": True}
            if page.source_kind == "browser_export"
            else {}
        )
        await self._content_repository.upsert_video_contents(
            tenant_id,
            page.query.shop_id,
            content_items,
            external_id_field="videoId",
            platform_request_id=page.request_id,
            **content_options,
        )
        window_start, window_end = page.query.utc_window()
        return await self._performance_repository.upsert_page(
            tenant_id,
            page.query.shop_id,
            run_id,
            performance_items,
            window_start=window_start,
            window_end=window_end,
            currency=page.query.currency,
            account_type="AFFILIATE_ACCOUNTS",
            external_id_field="videoId",
            platform_request_id=page.request_id,
        )

    async def _store_covers(
        self,
        tenant_id: UUID,
        shop_id: UUID,
        records: list[AffiliateVideoMetricDTO],
    ) -> dict[str, str]:
        if self._cover_storage is None:
            return {}
        sources = {
            record.video_id: record.cover_image_url
            for record in records
            if record.cover_image_url
        }
        try:
            stored = await self._cover_storage.store_many(
                sources, tenant_id=tenant_id, shop_id=shop_id
            )
        except Exception:
            logger.warning("affiliate_video_cover_batch_store_failed", exc_info=True)
            return {}
        return {video_id: value.object_key for video_id, value in stored.items()}


def _content_item(
    record: AffiliateVideoMetricDTO, cover_object_key: str | None = None
) -> TikTokAnalyticsItem:
    fields = {
        "videoId": record.video_id,
        "creatorOpenId": record.creator_open_id,
        "sourceIdentifiers": dict(record.source_identifiers),
        "creatorUsername": record.creator_username,
        "creatorNickname": record.creator_nickname,
        "creatorAvatarUrl": record.creator_avatar_url,
        "creatorFollowerCount": record.creator_follower_count,
        "creatorAuthorType": record.creator_author_type,
        "title": record.title,
        "videoPostTime": _json_scalar(record.video_post_time),
        "durationSeconds": _json_scalar(record.duration_seconds),
        "coverImageUrl": record.cover_image_url,
        "playUrl": record.play_url,
        "playId": record.play_id,
        "width": record.width,
        "height": record.height,
        "hashTags": list(record.hashtags),
        "promotedProductIds": list(record.promoted_product_ids),
        "promotedProducts": [_product(product) for product in record.promoted_products],
        "extensions": dict(record.extensions),
    }
    if cover_object_key:
        fields["coverImageObjectKey"] = cover_object_key
    return TikTokAnalyticsItem(
        fields=fields,
        source_status=None,
        status=record.status,
        source_updated_at=record.source_updated_at,
    )


def _performance_item(record: AffiliateVideoMetricDTO) -> TikTokAnalyticsItem:
    fields = {
        "videoId": record.video_id,
        "gmvMinor": record.gmv_minor,
        "estimatedCommissionMinor": record.estimated_commission_minor,
        "averageOrderValueMinor": record.average_order_value_minor,
        "averageGmvPerBuyerMinor": record.average_gmv_per_buyer_minor,
        "refundedGmvMinor": record.refunded_gmv_minor,
        "distinctGpmMinor": record.distinct_gpm_minor,
        "orderCount": record.order_count,
        "itemsSold": record.items_sold,
        "refundedItems": record.refunded_items,
        "productImpressions": record.product_impressions,
        "productClicks": record.product_clicks,
        "views": record.views,
        "likes": record.likes,
        "comments": record.comments,
        "shares": record.shares,
        "productClickThroughRate": record.product_click_through_rate,
        "engagementRate": record.engagement_rate,
        "finishRate": record.finish_rate,
        "extensions": dict(record.extensions),
    }
    return TikTokAnalyticsItem(
        fields=fields,
        source_status=None,
        status=record.status,
        source_updated_at=record.source_updated_at,
    )


def _product(product: AffiliateVideoProductDTO) -> dict[str, object]:
    return {
        "productId": product.product_id,
        "title": product.title,
        "coverImageUrl": product.cover_image_url,
        "extensions": dict(product.extensions),
    }


def _json_scalar(value: datetime | Decimal | None) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value) if isinstance(value, Decimal) else None
