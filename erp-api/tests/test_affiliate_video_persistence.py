import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from erp_api.services.affiliate_center_contract import (
    AffiliateCenterQuery,
    AffiliateCenterResource,
)
from erp_api.services.affiliate_center_metric_dtos import AffiliateVideoMetricDTO
from erp_api.services.affiliate_center_source import (
    AffiliateCenterPageDTO,
    AffiliatePaginationDTO,
)
from erp_api.services.affiliate_video_persistence import AffiliateVideoPersistence


class FakeContentRepository:
    def __init__(self, *, failure=None) -> None:
        self.calls = []
        self.failure = failure

    async def upsert_video_contents(self, *args, **kwargs):
        if self.failure:
            raise self.failure
        self.calls.append((args, kwargs))
        return len(args[2])


class FakePerformanceRepository:
    def __init__(self) -> None:
        self.calls = []

    async def upsert_page(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return len(args[3])


class FakeCoverStorage:
    def __init__(self) -> None:
        self.calls = []

    async def store_many(self, sources, **kwargs):
        self.calls.append((sources, kwargs))
        return {
            video_id: SimpleNamespace(object_key="affiliate/video-covers/stored.webp")
            for video_id in sources
        }


def _page(
    *,
    source_kind: str = "page_capture",
    cover_image_url: str | None = None,
) -> AffiliateCenterPageDTO:
    query = AffiliateCenterQuery(
        resource=AffiliateCenterResource.VIDEOS,
        shop_id=uuid4(),
        window_start=datetime(2026, 8, 1, tzinfo=UTC).date(),
        window_end=datetime(2026, 8, 7, tzinfo=UTC).date(),
        shop_timezone="America/Los_Angeles",
        currency="USD",
        filters={},
    )
    record = AffiliateVideoMetricDTO(
        video_id="video-1",
        window_start_utc=query.utc_window()[0],
        window_end_utc=query.utc_window()[1],
        shop_timezone=query.shop_timezone,
        currency=query.currency,
        creator_open_id="open-1",
        source_identifiers={"tiktok_page_creator_id": "private-1"},
        creator_username="@creator",
        title="Video title",
        cover_image_url=cover_image_url,
        video_post_time=datetime(2026, 8, 2, tzinfo=UTC),
        duration_seconds=Decimal("12.5"),
        promoted_product_ids=("product-1",),
        gmv_minor=1234,
        order_count=2,
        views=300,
        product_click_through_rate="0.05",
        extensions={"video_metrics": {"newMetric": "kept"}},
    )
    return AffiliateCenterPageDTO(
        source_kind=source_kind,
        query=query,
        records=(record,),
        pagination=AffiliatePaginationDTO(
            mode="unknown", page_number=1, next_cursor=None, has_more=False
        ),
        request_id="request-1",
        source_updated_at=None,
        raw_payload={"data": {}},
    )


def test_video_dto_is_written_to_content_and_performance_snapshots() -> None:
    content = FakeContentRepository()
    performance = FakePerformanceRepository()
    service = AffiliateVideoPersistence(content, performance)
    page, tenant_id, run_id = _page(), uuid4(), uuid4()

    persisted = asyncio.run(service.persist_page(tenant_id, run_id, page))

    assert persisted == 1
    content_item = content.calls[0][0][2][0]
    assert content.calls[0][0][1] == page.query.shop_id
    assert content.calls[0][1] == {
        "external_id_field": "videoId",
        "platform_request_id": "request-1",
    }
    assert content_item.fields["videoId"] == "video-1"
    assert content_item.fields["creatorOpenId"] == "open-1"
    assert content_item.fields["videoPostTime"] == "2026-08-02T00:00:00+00:00"
    assert content_item.fields["durationSeconds"] == "12.5"
    assert "gmvMinor" not in content_item.fields

    performance_call = performance.calls[0]
    performance_item = performance_call[0][3][0]
    assert performance_call[0][1:3] == (page.query.shop_id, run_id)
    assert performance_call[1]["window_start"] == page.query.utc_window()[0]
    assert performance_call[1]["window_end"] == page.query.utc_window()[1]
    assert performance_call[1]["currency"] == "USD"
    assert performance_call[1]["account_type"] == "AFFILIATE_ACCOUNTS"
    assert performance_item.fields == {
        "videoId": "video-1",
        "gmvMinor": 1234,
        "estimatedCommissionMinor": None,
        "averageOrderValueMinor": None,
        "averageGmvPerBuyerMinor": None,
        "refundedGmvMinor": None,
        "distinctGpmMinor": None,
        "orderCount": 2,
        "itemsSold": None,
        "refundedItems": None,
        "productImpressions": None,
        "productClicks": None,
        "views": 300,
        "likes": None,
        "comments": None,
        "shares": None,
        "productClickThroughRate": "0.05",
        "engagementRate": None,
        "finishRate": None,
        "extensions": {"video_metrics": {"newMetric": "kept"}},
    }


def test_browser_export_does_not_overwrite_existing_video_media() -> None:
    content = FakeContentRepository()
    performance = FakePerformanceRepository()
    service = AffiliateVideoPersistence(content, performance)

    asyncio.run(
        service.persist_page(uuid4(), uuid4(), _page(source_kind="browser_export"))
    )

    assert content.calls[0][1]["preserve_existing_details"] is True


def test_fresh_video_cover_is_stored_with_the_content_record() -> None:
    content = FakeContentRepository()
    performance = FakePerformanceRepository()
    covers = FakeCoverStorage()
    service = AffiliateVideoPersistence(content, performance, cover_storage=covers)
    page = _page(cover_image_url="https://p16-common-sign.tiktokcdn-us.com/cover.webp")
    tenant_id = uuid4()

    asyncio.run(service.persist_page(tenant_id, uuid4(), page))

    content_item = content.calls[0][0][2][0]
    assert content_item.fields["coverImageObjectKey"] == (
        "affiliate/video-covers/stored.webp"
    )
    assert covers.calls == [
        (
            {"video-1": ("https://p16-common-sign.tiktokcdn-us.com/cover.webp")},
            {
                "tenant_id": tenant_id,
                "shop_id": page.query.shop_id,
            },
        )
    ]


def test_content_failure_prevents_performance_and_cursor_eligible_success() -> None:
    content = FakeContentRepository(failure=RuntimeError("content failed"))
    performance = FakePerformanceRepository()
    service = AffiliateVideoPersistence(content, performance)

    with pytest.raises(RuntimeError, match="content failed"):
        asyncio.run(service.persist_page(uuid4(), uuid4(), _page()))

    assert performance.calls == []


def test_creator_page_is_rejected_by_video_persistence() -> None:
    page = SimpleNamespace(resource=AffiliateCenterResource.CREATORS)
    service = AffiliateVideoPersistence(
        FakeContentRepository(), FakePerformanceRepository()
    )

    with pytest.raises(ValueError, match="video resource"):
        asyncio.run(service.persist_page(uuid4(), uuid4(), page))
