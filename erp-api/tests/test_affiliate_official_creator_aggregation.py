from datetime import UTC, datetime

from erp_api.services.affiliate_center_metric_dtos import AffiliateVideoMetricDTO
from erp_api.services.affiliate_official_creator_aggregation import (
    aggregate_official_video_creators,
)


def _video(video_id: str, *, gmv: int, orders: int, items: int):
    return AffiliateVideoMetricDTO(
        video_id=video_id,
        window_start_utc=datetime(2026, 8, 24, tzinfo=UTC),
        window_end_utc=datetime(2026, 8, 25, tzinfo=UTC),
        shop_timezone="America/Los_Angeles",
        currency="USD",
        creator_open_id="creator-1",
        creator_username="@creator",
        gmv_minor=gmv,
        order_count=orders,
        items_sold=items,
    )


def test_creator_metrics_are_aggregated_only_from_the_same_official_video_page() -> None:
    rows = aggregate_official_video_creators(
        [
            _video("video-1", gmv=1000, orders=1, items=2),
            _video("video-2", gmv=2500, orders=3, items=4),
        ]
    )

    assert rows == [
        {
            "creatorOpenId": "creator-1",
            "username": "@creator",
            "avatarUrl": None,
            "currency": "USD",
            "affiliateGmvMinor": 3500,
            "affiliateVideoGmvMinor": 3500,
            "affiliateProductItemsSold": 6,
            "itemsSold": 6,
            "affiliateOrderCount": 4,
            "productImpressions": None,
            "affiliateVideoCount": 2,
            "affiliateFollowerCount": None,
            "estimatedCommissionMinor": None,
        }
    ]
