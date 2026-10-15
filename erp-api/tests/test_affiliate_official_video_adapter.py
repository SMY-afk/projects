from datetime import date
from uuid import uuid4

from erp_api.services.affiliate_center_contract import (
    AffiliateCenterQuery,
    AffiliateCenterResource,
)
from erp_api.services.affiliate_video_metric_parser import parse_video_official_items
from erp_api.services.tiktok_data_schemas import TikTokAnalyticsItem


def test_official_shop_video_fields_are_normalized_for_affiliate_storage() -> None:
    query = AffiliateCenterQuery(
        resource=AffiliateCenterResource.VIDEOS,
        shop_id=uuid4(),
        window_start=date(2026, 8, 24),
        window_end=date(2026, 8, 30),
        shop_timezone="America/Los_Angeles",
        currency="USD",
        filters={},
    )
    item = TikTokAnalyticsItem(
        fields={
            "videoId": "video-1",
            "username": "fallback_user",
            "creatorOpenId": "creator-1",
            "creatorUsername": "creator_user",
            "creatorNickname": "Creator",
            "creatorAuthorType": "AFFILIATE_ACCOUNTS",
            "videoPostTime": "2026-08-24 12:30:00",
            "gmvAmount": "1645.65",
            "gmvCurrency": "USD",
            "gpmAmount": "28.13",
            "gpmCurrency": "USD",
            "skuOrders": 18,
            "itemsSold": 19,
            "views": 58601,
            "clickThroughRate": "0.0174",
            "hashTags": ["toy", "toy", "fyp"],
            "promotedProducts": [{"id": "product-1", "name": "Toy"}],
        },
        source_status=None,
        status=None,
        source_updated_at=None,
    )

    record = parse_video_official_items([item], query=query)[0]

    assert record.creator_username == "creator_user"
    assert record.gmv_minor == 164565
    assert record.distinct_gpm_minor == 2813
    assert record.order_count == 18
    assert record.items_sold == 19
    assert record.views == 58601
    assert record.product_click_through_rate == "0.0174"
    assert record.video_post_time is not None
    assert record.hashtags == ("toy", "fyp")
    assert record.promoted_products[0].product_id == "product-1"
    assert record.promoted_products[0].title == "Toy"


def test_official_shop_video_accepts_platform_click_rate_above_one() -> None:
    query = AffiliateCenterQuery(
        resource=AffiliateCenterResource.VIDEOS,
        shop_id=uuid4(),
        window_start=date(2026, 8, 31),
        window_end=date(2026, 8, 31),
        shop_timezone="America/Los_Angeles",
        currency="USD",
        filters={},
    )
    item = TikTokAnalyticsItem(
        fields={
            "videoId": "video-high-ctr",
            "creatorOpenId": "creator-1",
            "gmvAmount": "0",
            "gmvCurrency": "USD",
            "clickThroughRate": "1.74",
        },
        source_status=None,
        status=None,
        source_updated_at=None,
    )

    record = parse_video_official_items([item], query=query)[0]

    assert record.product_click_through_rate == "1.74"
