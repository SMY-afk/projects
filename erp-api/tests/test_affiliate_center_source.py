import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from uuid import UUID

from erp_api.services.affiliate_center_contract import (
    AffiliateCenterQuery,
    AffiliateCenterResource,
)
from erp_api.services.affiliate_center_source import (
    AffiliateCenterPageDTO,
    AffiliateCenterSource,
    AffiliatePaginationDTO,
    AffiliateSourcePageContext,
)
from erp_api.services.affiliate_center_source_adapters import (
    map_browser_export_creator_page,
    map_official_creator_page,
    map_official_video_page,
    map_page_capture,
)
from erp_api.services.tiktok_data_schemas import TikTokAnalyticsItem


def _query() -> AffiliateCenterQuery:
    return AffiliateCenterQuery(
        resource=AffiliateCenterResource.CREATORS,
        shop_id=UUID("e4408786-af60-545e-8f8c-5ef22a71e675"),
        window_start=date(2026, 8, 1),
        window_end=date(2026, 8, 7),
        shop_timezone="America/Los_Angeles",
        currency="USD",
        filters={},
    )


def _page_payload() -> dict[str, object]:
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "segments": [
                {
                    "filter": {"shop_id": "shop-1"},
                    "list_control": {
                        "next_pagination": {
                            "has_more": True,
                            "next_page": 2,
                            "total": 2,
                            "total_page": 2,
                        },
                        "rules": [],
                    },
                    "time_descriptor": {
                        "start": "2026-08-01",
                        "end": "2026-08-07",
                        "timezone_offset": -7,
                    },
                    "timed_lists": [
                        {
                            "start": "2026-08-01",
                            "end": "2026-08-07",
                            "stats": [
                                {
                                    "id": "creator-1",
                                    "handle": "@creator",
                                    "revenue": {
                                        "amount": "12.34",
                                        "currency_code": "USD",
                                    },
                                    "order_cnt": 2,
                                }
                            ],
                        }
                    ],
                }
            ]
        },
    }


def _video_query() -> AffiliateCenterQuery:
    return _query().with_resource(AffiliateCenterResource.VIDEOS)


def _video_page_payload() -> dict[str, object]:
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
                            },
                            "product_base_list": [],
                            "product_ids": [],
                            "video_info": {
                                "item_id": "video-1",
                                "create_time": "1787616000",
                                "play_info": {},
                            },
                            "video_metrics": {
                                "video_gmv": {
                                    "amount": "12.34",
                                    "currency_code": "USD",
                                },
                                "video_orders_cnt": {"value": "0"},
                                "video_product_impressions_cnt": {"value": "0"},
                                "video_views_cnt": {"value": "0"},
                            },
                        }
                    ],
                }
            ]
        },
    }


def test_page_and_official_adapters_emit_the_same_page_dto() -> None:
    page = map_page_capture(
        _query(),
        _page_payload(),
        context=AffiliateSourcePageContext(
            request_id="page-request",
            pagination_mode="page_page_size",
            page_number=1,
        ),
    )
    official = map_official_creator_page(
        _query(),
        [
            {
                "username": "@creator",
                "creatorOpenId": "open-1",
                "currency": "USD",
                "affiliateGmvMinor": 1234,
                "affiliateOrderCount": 2,
            }
        ],
        context=AffiliateSourcePageContext(
            request_id="official-request",
            pagination_mode="cursor",
            next_cursor="cursor-2",
            has_more=True,
            total_count=2,
        ),
        raw_payload={"data": {"creators": []}},
    )

    assert isinstance(page, AffiliateCenterPageDTO)
    assert isinstance(official, AffiliateCenterPageDTO)
    assert type(page) is type(official)
    assert page.resource is AffiliateCenterResource.CREATORS
    assert official.resource is AffiliateCenterResource.CREATORS
    assert page.records[0].affiliate_gmv_minor == 1234
    assert official.records[0].affiliate_gmv_minor == 1234
    assert page.pagination == AffiliatePaginationDTO(
        mode="page_page_size",
        page_number=1,
        page_size=None,
        offset=None,
        next_cursor="page:2",
        has_more=True,
        total_count=2,
    )
    assert official.pagination.next_cursor == "cursor-2"


def test_browser_export_adapter_emits_the_shared_creator_page_dto() -> None:
    exported = map_browser_export_creator_page(
        _query(),
        [
            {
                "username": "@creator",
                "currency": "USD",
                "affiliateGmvMinor": 1234,
                "affiliateOrderCount": 2,
            }
        ],
        context=AffiliateSourcePageContext(
            request_id="export-request",
            pagination_mode="unknown",
            page_number=1,
            page_size=1,
            has_more=False,
            total_count=1,
        ),
        raw_payload={"export": {"recordCount": 1}},
    )

    assert isinstance(exported, AffiliateCenterPageDTO)
    assert exported.source_kind == "browser_export"
    assert exported.raw_payload_kind == "affiliate_creator_export"
    assert exported.records[0].affiliate_gmv_minor == 1234
    assert exported.pagination.total_count == 1


def test_source_protocol_is_shared_by_push_and_official_sources() -> None:
    page = map_page_capture(
        _query(),
        _page_payload(),
        context=AffiliateSourcePageContext(
            request_id="request-1",
            pagination_mode="page_page_size",
            page_number=1,
        ),
    )

    class Source:
        source_kind = "page_capture"

        async def iter_pages(
            self, query, *, start_cursor=None
        ) -> AsyncIterator[AffiliateCenterPageDTO]:
            yield page

    source: AffiliateCenterSource = Source()

    async def collect() -> list[AffiliateCenterPageDTO]:
        return [item async for item in source.iter_pages(_query())]

    assert isinstance(source, AffiliateCenterSource)
    assert asyncio.run(collect()) == [page]


def test_video_page_and_official_adapters_emit_the_same_page_dto() -> None:
    captured = map_page_capture(
        _video_query(),
        _video_page_payload(),
        context=AffiliateSourcePageContext(
            request_id="page-video-request",
            pagination_mode="unknown",
        ),
    )
    official = map_official_video_page(
        _video_query(),
        [
            TikTokAnalyticsItem(
                fields={
                    "videoId": "video-1",
                    "currency": "USD",
                    "gmvMinor": 1234,
                },
                source_status=None,
                status=None,
                source_updated_at=datetime(2026, 8, 8, tzinfo=UTC),
            )
        ],
        context=AffiliateSourcePageContext(
            request_id="official-video-request",
            pagination_mode="cursor",
            has_more=False,
        ),
        raw_payload={"data": {"videos": []}},
    )

    assert type(captured) is type(official) is AffiliateCenterPageDTO
    assert captured.records[0].video_id == official.records[0].video_id == "video-1"
    assert captured.records[0].gmv_minor == official.records[0].gmv_minor == 1234
    assert captured.pagination.mode == "unknown"
    assert captured.pagination.next_cursor is None
    assert captured.pagination.total_count == 1


def test_unknown_pagination_is_preserved_without_guessing_cursor() -> None:
    pagination = AffiliatePaginationDTO(mode="unknown", total_count=10)

    assert pagination.mode == "unknown"
    assert pagination.next_cursor is None
    assert pagination.has_more is None
