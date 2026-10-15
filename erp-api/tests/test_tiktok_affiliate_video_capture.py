import asyncio
from datetime import UTC, date, datetime
from types import SimpleNamespace
from uuid import uuid4

from backend.app.services.tiktok_affiliate_analytics_context import (
    AffiliateAnalyticsResponseContext,
)
from backend.app.services.tiktok_affiliate_video_capture import (
    TikTokAffiliateVideoCaptureSession,
    _payload_window,
)


class FakeReadRepository:
    def __init__(self, shop_id) -> None:
        self.shop_id = shop_id
        self.calls = []

    async def get_shop_context_by_platform_id(self, tenant_id, platform_shop_id):
        self.calls.append((tenant_id, platform_shop_id))
        return {
            "shopId": self.shop_id,
            "shopTimezone": "America/Los_Angeles",
            "currency": "USD",
        }


class FakeSyncRepository:
    def __init__(self, run_id) -> None:
        self.run_id = run_id
        self.events = []

    async def has_recorded_page(self, *args, **kwargs):
        return False

    async def create_run(self, tenant_id, shop_id, **kwargs):
        self.events.append(("create", tenant_id, shop_id, kwargs))
        return self.run_id

    async def start_run(self, tenant_id, run_id):
        self.events.append(("start", tenant_id, run_id))

    async def record_page(self, tenant_id, run_id, **kwargs):
        self.events.append(("cursor", tenant_id, run_id, kwargs))

    async def complete_run(self, tenant_id, run_id, **kwargs):
        self.events.append(("complete", tenant_id, run_id, kwargs))
        return SimpleNamespace(status="succeeded")

    async def partial_run(self, tenant_id, run_id, **kwargs):
        self.events.append(("partial", tenant_id, run_id, kwargs))
        return SimpleNamespace(status="partial")


class FakePersistence:
    def __init__(self, events) -> None:
        self.events = events
        self.pages = []

    async def persist_page(self, tenant_id, run_id, page):
        self.events.append(("details", tenant_id, run_id))
        self.pages.append(page)
        return len(page.records)


def _payload() -> dict[str, object]:
    start = int(datetime(2026, 8, 1, 7, tzinfo=UTC).timestamp())
    end = int(datetime(2026, 8, 8, 6, 59, 59, tzinfo=UTC).timestamp())
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "video_list_segments_v2": [
                {
                    "time_descriptor": {
                        "start_time": start,
                        "end_time": end,
                        "timezone_offset": -7,
                    },
                    "total": 1,
                    "video_performances": [
                        {
                            "creator_base": {
                                "oec_id": "creator-private-1",
                                "handle_name": "@creator",
                            },
                            "product_base_list": [],
                            "product_ids": [],
                            "video_info": {
                                "item_id": "video-1",
                                "create_time": "1785654000",
                                "title": "Video",
                                "play_info": {},
                            },
                            "video_metrics": {
                                "video_gmv": {
                                    "amount": "12.34",
                                    "currency_code": "USD",
                                },
                                "video_orders_cnt": {"value": "2"},
                                "video_product_impressions_cnt": {"value": "100"},
                                "video_views_cnt": {"value": "300"},
                            },
                        }
                    ],
                }
            ]
        },
    }


def _observation() -> dict[str, object]:
    return {"pagination": {"mode": "unknown"}}


def _build():
    tenant_id, shop_id, run_id = uuid4(), uuid4(), uuid4()
    sync = FakeSyncRepository(run_id)
    persistence = FakePersistence(sync.events)
    service = TikTokAffiliateVideoCaptureSession(
        tenant_id,
        FakeReadRepository(shop_id),  # type: ignore[arg-type]
        sync,  # type: ignore[arg-type]
        persistence,  # type: ignore[arg-type]
    )
    context = AffiliateAnalyticsResponseContext("platform-shop-1", "request-1")
    return service, sync, persistence, context, tenant_id, shop_id, run_id


def test_capture_maps_dto_then_writes_details_before_recovery_cursor() -> None:
    service, sync, persistence, context, tenant_id, shop_id, run_id = _build()

    asyncio.run(
        service.persist_page("videos", _payload(), _observation(), context, 1, None)
    )

    assert [event[0] for event in sync.events] == [
        "create",
        "start",
        "details",
        "cursor",
    ]
    create = sync.events[0]
    assert create[1:3] == (tenant_id, shop_id)
    assert create[3]["resource_type"] == "affiliate_video"
    assert create[3]["currency"] == "USD"
    assert create[3]["account_type"] == "AFFILIATE_ACCOUNTS"
    assert persistence.pages[0].records[0].video_id == "video-1"
    assert persistence.pages[0].records[0].gmv_minor == 1234
    assert persistence.pages[0].query.window_start.isoformat() == "2026-08-01"
    assert persistence.pages[0].query.window_end.isoformat() == "2026-08-07"
    cursor = sync.events[-1]
    assert cursor[1:3] == (tenant_id, run_id)
    assert cursor[3]["next_cursor"] is None
    assert cursor[3]["persisted_count"] == 1
    assert cursor[3]["platform_request_id"] == "request-1"


def test_payload_window_uses_platform_fixed_offset_during_dst() -> None:
    payload = _payload()
    descriptor = payload["data"]["video_list_segments_v2"][0]["time_descriptor"]
    descriptor.update(
        {
            "start_time": int(datetime(2026, 8, 17, 8, tzinfo=UTC).timestamp()),
            "end_time": int(datetime(2026, 8, 24, 8, tzinfo=UTC).timestamp()),
            "timezone_offset": -28800,
        }
    )

    assert _payload_window(payload, "America/Los_Angeles") == (
        date(2026, 8, 17),
        date(2026, 8, 23),
    )


def test_complete_and_partial_terminal_states_are_committed_once() -> None:
    complete, complete_sync, _, context, *_ = _build()
    asyncio.run(
        complete.persist_page("videos", _payload(), _observation(), context, 1, None)
    )
    asyncio.run(
        complete.finalize_resource(
            "videos", {"status": "complete", "failure_category": None}
        )
    )
    asyncio.run(
        complete.finalize_resource(
            "videos", {"status": "complete", "failure_category": None}
        )
    )
    assert [event[0] for event in complete_sync.events].count("complete") == 1

    partial, partial_sync, _, context, *_ = _build()
    asyncio.run(
        partial.persist_page("videos", _payload(), _observation(), context, 1, None)
    )
    asyncio.run(
        partial.finalize_resource(
            "videos", {"status": "partial", "failure_category": "max_pages_exceeded"}
        )
    )
    assert partial_sync.events[-1][0] == "partial"
    assert partial_sync.events[-1][3] == {"reason": "page_failed"}
