from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

import pytest

from erp_api.services.affiliate_center_contract import (
    AffiliateCenterQuery,
    AffiliateCenterResource,
)
from erp_api.services.affiliate_center_metric_dtos import (
    AffiliateVideoMetricDTO,
    AffiliateVideoProductDTO,
)
from erp_api.services.affiliate_video_metric_parser import (
    AffiliateVideoMetricParseError,
    parse_video_export_rows,
    parse_video_official_items,
    parse_video_page_payload,
)
from erp_api.services.tiktok_data_schemas import TikTokAnalyticsItem


def _page_payload() -> dict[str, object]:
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "video_list_segments_v2": [
                {
                    "time_descriptor": {
                        "start_time": 1,
                        "end_time": 2,
                        "timezone_offset": -7,
                    },
                    "total": 1,
                    "video_performances": [
                        {
                            "creator_base": {
                                "oec_id": "creator-1",
                                "handle_name": "@creator",
                                "nick_name": "Creator",
                                "follower_cnt": "25K",
                                "avatar": {
                                    "thumb_url_list": [
                                        "https://example.test/avatar.jpg"
                                    ]
                                },
                            },
                            "product_base_list": [
                                {
                                    "id": "product-1",
                                    "title": "Product",
                                    "cover": {
                                        "thumb_url_list": [
                                            "https://example.test/product.jpg"
                                        ]
                                    },
                                }
                            ],
                            "product_ids": ["product-1"],
                            "video_info": {
                                "item_id": "video-1",
                                "create_time": "1787616000",
                                "title": "Video title",
                                "cover": "https://example.test/cover.jpg",
                                "play_info": {
                                    "duration": "15.5",
                                    "width": "1080",
                                    "height": "1920",
                                    "play_urls": ["https://example.test/video.mp4"],
                                },
                            },
                            "video_metrics": {
                                "video_gmv": {
                                    "amount": "12.34",
                                    "currency_code": "USD",
                                },
                                "video_estimated_commission": {
                                    "amount": "1.23",
                                    "currency_code": "USD",
                                },
                                "video_orders_cnt": {"value": "2"},
                                "video_items_sold_cnt": {"value": "3"},
                                "video_product_impressions_cnt": {"value": "1.2K"},
                                "video_product_clicks_cnt": {"value": "60"},
                                "video_views_cnt": {"value": "300"},
                                "video_likes_cnt": {"value": "30"},
                                "video_comments_cnt": {"value": "4"},
                                "video_shares_cnt": {"value": "5"},
                                "video_distinct_product_ctr": {"value": "5%"},
                                "video_distinct_engagement_rate": {"value": "13%"},
                                "unverified_rate": {"value": "9%"},
                                "phone": "private",
                            },
                        }
                    ],
                }
            ]
        },
    }


def _query() -> AffiliateCenterQuery:
    return AffiliateCenterQuery(
        resource=AffiliateCenterResource.VIDEOS,
        shop_id=UUID("e4408786-af60-545e-8f8c-5ef22a71e675"),
        window_start=date(2026, 8, 1),
        window_end=date(2026, 8, 7),
        shop_timezone="America/Los_Angeles",
        currency="USD",
        filters={},
    )


def test_video_page_payload_maps_zero_total_with_omitted_rows() -> None:
    payload = _page_payload()
    segment = payload["data"]["video_list_segments_v2"][0]
    segment["total"] = 0
    del segment["video_performances"]

    assert parse_video_page_payload(payload, query=_query()) == []


def test_video_page_payload_maps_to_domain_dto() -> None:
    result = parse_video_page_payload(_page_payload(), query=_query())

    assert result == [
        AffiliateVideoMetricDTO(
            video_id="video-1",
            window_start_utc=datetime(2026, 8, 1, 7, tzinfo=UTC),
            window_end_utc=datetime(2026, 8, 8, 7, tzinfo=UTC),
            shop_timezone="America/Los_Angeles",
            source_identifiers={"tiktok_page_creator_id": "creator-1"},
            creator_username="@creator",
            creator_nickname="Creator",
            creator_avatar_url="https://example.test/avatar.jpg",
            creator_follower_count=25000,
            title="Video title",
            video_post_time=datetime(2026, 8, 25, tzinfo=UTC),
            duration_seconds=Decimal("15.5"),
            cover_image_url="https://example.test/cover.jpg",
            play_url="https://example.test/video.mp4",
            width=1080,
            height=1920,
            promoted_product_ids=("product-1",),
            promoted_products=(
                AffiliateVideoProductDTO(
                    product_id="product-1",
                    title="Product",
                    cover_image_url="https://example.test/product.jpg",
                ),
            ),
            currency="USD",
            gmv_minor=1234,
            estimated_commission_minor=123,
            order_count=2,
            items_sold=3,
            product_impressions=1200,
            product_clicks=60,
            views=300,
            likes=30,
            comments=4,
            shares=5,
            product_click_through_rate="0.05",
            engagement_rate="0.13",
            extensions={"video_metrics": {"unverified_rate": {"value": "9%"}}},
        )
    ]


def test_video_product_click_through_rate_accepts_platform_values_above_one() -> None:
    payload = _page_payload()
    metrics = payload["data"]["video_list_segments_v2"][0]["video_performances"][0][
        "video_metrics"
    ]
    metrics["video_distinct_product_ctr"] = {
        "value": "2",
        "value_formatted": "200%",
    }

    result = parse_video_page_payload(payload, query=_query())

    assert result[0].product_click_through_rate == "2"


def test_video_engagement_rate_accepts_multiple_interactions_per_view() -> None:
    payload = _page_payload()
    metrics = payload["data"]["video_list_segments_v2"][0]["video_performances"][0][
        "video_metrics"
    ]
    metrics["video_distinct_engagement_rate"] = {
        "value": "1.5",
        "value_formatted": "150%",
    }

    result = parse_video_page_payload(payload, query=_query())

    assert result[0].engagement_rate == "1.5"


def test_video_page_accepts_millisecond_timestamp_string() -> None:
    payload = _page_payload()
    video = payload["data"]["video_list_segments_v2"][0]["video_performances"][0][
        "video_info"
    ]
    video["create_time"] = "1787616000000"

    result = parse_video_page_payload(payload, query=_query())

    assert result[0].video_post_time == datetime(2026, 8, 25, tzinfo=UTC)


def test_video_page_accepts_missing_play_info() -> None:
    payload = _page_payload()
    video = payload["data"]["video_list_segments_v2"][0]["video_performances"][0][
        "video_info"
    ]
    video.pop("play_info")

    result = parse_video_page_payload(payload, query=_query())

    assert result[0].video_id == "video-1"
    assert result[0].duration_seconds is None
    assert result[0].play_url is None
    assert result[0].width is None
    assert result[0].height is None


def test_video_page_treats_empty_cover_object_as_missing() -> None:
    payload = _page_payload()
    video = payload["data"]["video_list_segments_v2"][0]["video_performances"][0][
        "video_info"
    ]
    video["cover"] = {}

    result = parse_video_page_payload(payload, query=_query())

    assert result[0].cover_image_url is None


def test_video_official_and_export_rows_produce_identical_dto() -> None:
    canonical = {
        "videoId": "video-1",
        "creatorId": "private-creator-1",
        "creatorOpenId": "creator-1",
        "creator_id": "similar-name-must-not-map",
        "creatorUsername": "@creator",
        "title": "Video title",
        "videoPostTime": "2026-08-25T00:00:00+00:00",
        "durationSeconds": "15.5",
        "promotedProductIds": ["product-1"],
        "currency": "USD",
        "gmvMinor": "1234",
        "views": "300",
        "productClickThroughRate": "1.25",
        "status": "published",
        "sourceUpdatedAt": "2026-08-25T00:00:00+00:00",
    }
    official = parse_video_official_items(
        [
            TikTokAnalyticsItem(
                canonical,
                "PUBLISHED",
                "published",
                datetime(2026, 8, 25, 8, tzinfo=timezone(timedelta(hours=8))),
            )
        ],
        query=_query(),
    )[0]
    exported = parse_video_export_rows([canonical], query=_query())[0]

    assert isinstance(official, AffiliateVideoMetricDTO)
    assert official == exported
    assert official.creator_open_id == "creator-1"
    assert official.source_identifiers == {"official_creator_id": "private-creator-1"}
    assert official.extensions == {"creator_id": "similar-name-must-not-map"}
    assert official.product_click_through_rate == "1.25"
    assert official.source_updated_at == datetime(2026, 8, 25, tzinfo=UTC)


def test_video_page_rejects_fractional_count() -> None:
    payload = _page_payload()
    metrics = payload["data"]["video_list_segments_v2"][0]["video_performances"][0][
        "video_metrics"
    ]
    metrics["video_views_cnt"] = {"value": "1.5"}

    with pytest.raises(AffiliateVideoMetricParseError, match="views"):
        parse_video_page_payload(payload, query=_query())


def test_video_export_rejects_float_minor_money() -> None:
    with pytest.raises(AffiliateVideoMetricParseError, match="float"):
        parse_video_export_rows(
            [{"videoId": "video-1", "currency": "USD", "gmvMinor": 1234.0}],
            query=_query(),
        )
