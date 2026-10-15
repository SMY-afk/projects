from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class AffiliateCreatorMetricDTO:
    username: str
    username_normalized: str
    window_start_utc: datetime
    window_end_utc: datetime
    shop_timezone: str
    currency: str
    creator_open_id: str | None = None
    source_identifiers: dict[str, str] = field(default_factory=dict)
    avatar_url: str | None = None
    affiliate_gmv_minor: int | None = None
    affiliate_live_gmv_minor: int | None = None
    affiliate_video_gmv_minor: int | None = None
    affiliate_showcase_gmv_minor: int | None = None
    affiliate_product_items_sold: int | None = None
    items_sold: int | None = None
    estimated_commission_minor: int | None = None
    estimated_flat_fee_minor: int | None = None
    average_order_amount_minor: int | None = None
    showcase_product_count: int | None = None
    affiliate_order_count: int | None = None
    click_through_rate: str | None = None
    product_impressions: int | None = None
    average_affiliate_customers: Decimal | None = None
    affiliate_live_count: int | None = None
    affiliate_video_count: int | None = None
    target_collaboration_gmv_minor: int | None = None
    target_collaboration_estimated_commission_minor: int | None = None
    open_collaboration_gmv_minor: int | None = None
    open_collaboration_estimated_commission_minor: int | None = None
    refunded_affiliate_gmv_minor: int | None = None
    refunded_affiliate_product_count: int | None = None
    affiliate_follower_count: int | None = None
    extensions: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class AffiliateVideoProductDTO:
    product_id: str
    title: str | None = None
    cover_image_url: str | None = None
    extensions: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class AffiliateVideoMetricDTO:
    video_id: str
    window_start_utc: datetime
    window_end_utc: datetime
    shop_timezone: str
    currency: str
    creator_open_id: str | None = None
    source_identifiers: dict[str, str] = field(default_factory=dict)
    creator_username: str | None = None
    creator_nickname: str | None = None
    creator_avatar_url: str | None = None
    creator_follower_count: int | None = None
    creator_author_type: str | None = None
    title: str | None = None
    video_post_time: datetime | None = None
    duration_seconds: Decimal | None = None
    cover_image_url: str | None = None
    play_url: str | None = None
    play_id: str | None = None
    width: int | None = None
    height: int | None = None
    hashtags: tuple[str, ...] = ()
    promoted_product_ids: tuple[str, ...] = ()
    promoted_products: tuple[AffiliateVideoProductDTO, ...] = ()
    status: str | None = None
    source_updated_at: datetime | None = None
    gmv_minor: int | None = None
    estimated_commission_minor: int | None = None
    average_order_value_minor: int | None = None
    average_gmv_per_buyer_minor: int | None = None
    refunded_gmv_minor: int | None = None
    distinct_gpm_minor: int | None = None
    order_count: int | None = None
    items_sold: int | None = None
    refunded_items: int | None = None
    product_impressions: int | None = None
    product_clicks: int | None = None
    views: int | None = None
    likes: int | None = None
    comments: int | None = None
    shares: int | None = None
    product_click_through_rate: str | None = None
    engagement_rate: str | None = None
    finish_rate: str | None = None
    extensions: dict[str, object] = field(default_factory=dict)
