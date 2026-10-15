from datetime import UTC, datetime

import pytest

from erp_api.services.tiktok_data_schemas import (
    classify_analytics_failure,
    parse_analytics_page,
)
from erp_api.services.tiktok_transport import TikTokApiError, TikTokRateLimitError


def test_analytics_dto_keeps_safe_metadata_and_maps_unknown_status() -> None:
    page = parse_analytics_page(
        {
            "data": {
                "updated_at": "2026-08-17T10:00:00Z",
                "videos": [
                    {"id": "video-1", "status": "NEW", "updated_at": "1700000000"}
                ],
                "next_page_token": "next",
            }
        },
        platform_request_id="platform-request-1",
        items_path="videos",
        next_page_token_path="next_page_token",
        field_map={"videoId": "id"},
        required_fields=("videoId",),
        source_updated_at_path="updated_at",
        item_source_updated_at_path="updated_at",
        status_path="status",
        status_map={"LIVE": "active"},
    )

    assert page.platform_request_id == "platform-request-1"
    assert page.source_updated_at == datetime(2026, 8, 17, 10, tzinfo=UTC)
    assert page.items[0].source_updated_at == datetime.fromtimestamp(
        1_700_000_000, tz=UTC
    )
    assert page.items[0].source_status == "NEW"
    assert page.items[0].status == "unknown"


def test_analytics_dto_rejects_missing_required_fields_and_classifies_safely() -> None:
    with pytest.raises(TikTokApiError, match="required fields") as error:
        parse_analytics_page(
            {"data": {"videos": [{}]}},
            platform_request_id="platform-request-2",
            items_path="videos",
            next_page_token_path=None,
            field_map={"videoId": "id"},
            required_fields=("videoId",),
            source_updated_at_path=None,
            item_source_updated_at_path=None,
            status_path=None,
            status_map={},
        )

    failure = classify_analytics_failure(error.value)
    assert failure.category == "missing_field"
    assert failure.platform_request_id == "platform-request-2"
    rate_limited = classify_analytics_failure(
        TikTokRateLimitError(retry_after_seconds=3, request_id="platform-request-3")
    )
    assert rate_limited.category == "rate_limited"
    assert rate_limited.retry_after_seconds == 3


def test_video_dto_preserves_verified_202605_operating_content_and_products() -> None:
    page = parse_analytics_page(
        {
            "data": {
                "videos": [
                    {
                        "id": "video-1",
                        "title": "Demo video",
                        "duration": 34,
                        "hash_tags": ["toys", "demo"],
                        "video_post_time": "2026-08-01 10:00:00",
                        "views": 1200,
                        "click_through_rate": "0.1250",
                        "avg_customers": 8,
                        "gmv": {"amount": "123.45", "currency": "USD"},
                        "gpm": {"amount": "10.29", "currency": "USD"},
                        "creator": {
                            "open_id": "creator-1",
                            "user_name": "creator_user",
                            "nick_name": "Creator",
                            "author_type": "AFFILIATE",
                        },
                        "products": [{"id": "product-1", "name": "Demo product"}],
                    }
                ]
            }
        },
        platform_request_id="request-1",
        items_path="videos",
        next_page_token_path="next_page_token",
        field_map={
            "videoId": "id",
            "title": "title",
            "durationSeconds": "duration",
            "hashTags": "hash_tags",
            "videoPostTime": "video_post_time",
            "views": "views",
            "clickThroughRate": "click_through_rate",
            "averageCustomers": "avg_customers",
            "gmvAmount": "gmv.amount",
            "gmvCurrency": "gmv.currency",
            "gpmAmount": "gpm.amount",
            "gpmCurrency": "gpm.currency",
            "creatorOpenId": "creator.open_id",
            "creatorUsername": "creator.user_name",
            "creatorNickname": "creator.nick_name",
            "creatorAuthorType": "creator.author_type",
            "promotedProducts": "products",
        },
        required_fields=("videoId",),
        source_updated_at_path=None,
        item_source_updated_at_path=None,
        status_path=None,
        status_map={},
    )

    assert page.items[0].fields == {
        "videoId": "video-1",
        "title": "Demo video",
        "durationSeconds": 34,
        "hashTags": ["toys", "demo"],
        "videoPostTime": "2026-08-01 10:00:00",
        "views": 1200,
        "clickThroughRate": "0.1250",
        "averageCustomers": 8,
        "gmvAmount": "123.45",
        "gmvCurrency": "USD",
        "gpmAmount": "10.29",
        "gpmCurrency": "USD",
        "creatorOpenId": "creator-1",
        "creatorUsername": "creator_user",
        "creatorNickname": "Creator",
        "creatorAuthorType": "AFFILIATE",
        "promotedProducts": [{"id": "product-1", "name": "Demo product"}],
    }


def test_live_dto_preserves_verified_202509_session_sales_fields() -> None:
    field_map = {
        "liveId": "id",
        "title": "title",
        "username": "username",
        "startTime": "start_time",
        "endTime": "end_time",
        "gmvAmount": "sales_performance.gmv.amount",
        "gmvCurrency": "sales_performance.gmv.currency",
        "productsAdded": "sales_performance.products_added",
        "differentProductsSold": "sales_performance.different_products_sold",
        "createdSkuOrders": "sales_performance.created_sku_orders",
        "skuOrders": "sales_performance.sku_orders",
        "itemsSold": "sales_performance.items_sold",
        "customers": "sales_performance.customers",
        "averagePriceAmount": "sales_performance.avg_price.amount",
        "averagePriceCurrency": "sales_performance.avg_price.currency",
        "clickToOrderRate": "sales_performance.click_to_order_rate",
        "clickThroughRate": "sales_performance.click_through_rate",
        "live24hGmvAmount": "sales_performance.24h_live_gmv.amount",
        "live24hGmvCurrency": "sales_performance.24h_live_gmv.currency",
    }
    page = parse_analytics_page(
        {
            "data": {
                "live_stream_sessions": [
                    {
                        "id": "live-1",
                        "title": "Demo LIVE",
                        "username": "creator",
                        "start_time": "1623812664",
                        "end_time": "1623812864",
                        "sales_performance": {
                            "gmv": {"amount": "99.00", "currency": "USD"},
                            "products_added": 12,
                            "different_products_sold": 5,
                            "created_sku_orders": 100,
                            "sku_orders": 80,
                            "items_sold": 122,
                            "customers": 50,
                            "avg_price": {"amount": "1.98", "currency": "USD"},
                            "click_to_order_rate": "0.25",
                            "24h_live_gmv": {"amount": "108.00", "currency": "USD"},
                        },
                    }
                ]
            }
        },
        platform_request_id="request-live-1",
        items_path="live_stream_sessions",
        next_page_token_path="next_page_token",
        field_map=field_map,
        required_fields=("liveId",),
        source_updated_at_path=None,
        item_source_updated_at_path=None,
        status_path=None,
        status_map={},
    )

    assert page.items[0].fields == {
        "liveId": "live-1",
        "title": "Demo LIVE",
        "username": "creator",
        "startTime": "1623812664",
        "endTime": "1623812864",
        "gmvAmount": "99.00",
        "gmvCurrency": "USD",
        "productsAdded": 12,
        "differentProductsSold": 5,
        "createdSkuOrders": 100,
        "skuOrders": 80,
        "itemsSold": 122,
        "customers": 50,
        "averagePriceAmount": "1.98",
        "averagePriceCurrency": "USD",
        "clickToOrderRate": "0.25",
        "clickThroughRate": None,
        "live24hGmvAmount": "108.00",
        "live24hGmvCurrency": "USD",
    }
