import asyncio
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from erp_api.services.analytics_sync_service import (
    AnalyticsSyncService,
    AnalyticsSyncWindowError,
)
from erp_api.services.analytics_sync_windows import initial_window_start, platform_dates
from erp_api.services.tiktok_data_schemas import (
    TikTokAnalyticsItem,
    TikTokAnalyticsPage,
)


class FakeSyncRepository:
    def __init__(self, committed_cursor=None) -> None:
        self.cursor = SimpleNamespace(committed_cursor=committed_cursor)
        self.created = []
        self.pages = []
        self.completed = []
        self.started = []
        self.failed = []
        self.cursor_reads = 0

    async def get_cursor(self, tenant_id, shop_id, resource_type):
        self.cursor_reads += 1
        return self.cursor

    async def create_run(self, tenant_id, shop_id, **kwargs):
        self.created.append(kwargs)
        return uuid4()

    async def start_run(self, tenant_id, run_id):
        self.started.append(run_id)

    async def record_page(self, tenant_id, run_id, **kwargs):
        self.pages.append(kwargs)

    async def complete_run(self, tenant_id, run_id, **kwargs):
        self.completed.append(kwargs)
        return SimpleNamespace(status="succeeded")

    async def fail_run(self, tenant_id, run_id, **kwargs):
        self.failed.append((run_id, kwargs))
        return SimpleNamespace(status="failed")


class FakeAnalyticsRepository:
    def __init__(self) -> None:
        self.video_calls = []
        self.live_calls = []
        self.snapshot_calls = []

    async def upsert_snapshots(self, *args, **kwargs):
        self.snapshot_calls.append((args, kwargs))
        return len(args[2])

    async def upsert_video_contents(self, *args, **kwargs):
        self.video_calls.append((args, kwargs))
        return len(args[2])

    async def upsert_live_sessions(self, *args, **kwargs):
        self.live_calls.append((args, kwargs))
        return len(args[2])


class FakeVideoPerformanceRepository:
    def __init__(self) -> None:
        self.calls = []

    async def upsert_page(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return len(args[3])


class FakeQualityRepository:
    def __init__(self) -> None:
        self.calls = []

    async def record_page_alerts(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return 0


class FakeShopRepository:
    async def get_authorized_tiktok_shop(self, tenant_id, shop_id):
        return {"id": shop_id, "timezone": "UTC"}

    async def get_access_token(self, tenant_id, shop_id):
        return "access-token"

    async def get_shop_cipher(self, tenant_id, shop_id):
        return "shop-cipher"


class FakeClient:
    def __init__(self) -> None:
        self.calls = []

    async def iter_videos(self, access_token, **kwargs):
        self.calls.append(("video", access_token, kwargs))
        yield TikTokAnalyticsPage(
            items=[
                TikTokAnalyticsItem(
                    fields={
                        "videoId": "video-1",
                        "title": "Video",
                        "views": 308,
                        "gmvAmount": "12.34",
                    },
                    source_status=None,
                    status=None,
                    source_updated_at=None,
                )
            ],
            next_page_token=None,
            platform_request_id="request-1",
            source_updated_at=datetime(2026, 8, 1, tzinfo=UTC),
            raw_payload={"data": {"videos": [{"id": "video-1"}]}},
        )

    async def iter_lives(self, access_token, **kwargs):
        self.calls.append(("live", access_token, kwargs))
        if False:
            yield None


class FakeOverviewClient:
    def __init__(self) -> None:
        self.calls = []

    async def get_overview(self, resource_type, access_token, **kwargs):
        self.calls.append((resource_type, access_token, kwargs))
        return SimpleNamespace(
            intervals=[
                {
                    "start_date": kwargs["start_date_ge"],
                    "end_date": (
                        datetime.fromisoformat(kwargs["start_date_ge"])
                        + timedelta(days=1)
                    )
                    .date()
                    .isoformat(),
                    "gmv": {"amount": "12.34", "currency": "USD"},
                    "sku_orders": 3,
                }
            ],
            platform_request_id="overview-request-1",
            latest_available_date=None,
            raw_payload={"data": {"performance": {"intervals": []}}},
        )


class NoDataOverviewClient(FakeOverviewClient):
    async def get_overview(self, resource_type, access_token, **kwargs):
        self.calls.append((resource_type, access_token, kwargs))
        return SimpleNamespace(
            intervals=[
                {
                    "start_date": kwargs["start_date_ge"],
                    "end_date": kwargs["end_date_lt"],
                    "sku_orders": 0,
                }
            ],
            platform_request_id="overview-no-data-request",
            latest_available_date=date(2026, 8, 17),
            raw_payload={
                "data": {
                    "latest_available_date": "2026-08-17",
                    "performance": {"intervals": []},
                }
            },
        )


def _service(
    committed_cursor=None,
    *,
    schedule_mode="daily",
    client=None,
    overview_client=None,
):
    sync_repository = FakeSyncRepository(committed_cursor)
    analytics_repository = FakeAnalyticsRepository()
    analytics_repository.performance_repository = FakeVideoPerformanceRepository()
    quality_repository = FakeQualityRepository()
    client = client or FakeClient()
    overview_client = overview_client or FakeOverviewClient()
    service = AnalyticsSyncService(
        sync_repository,
        analytics_repository,
        analytics_repository.performance_repository,
        quality_repository,
        FakeShopRepository(),
        client,
        overview_client,
        video_external_id_field="videoId",
        live_external_id_field="liveId",
        video_amount_currency_pairs={},
        live_amount_currency_pairs={},
        schedule_mode=schedule_mode,
    )
    return (
        service,
        sync_repository,
        analytics_repository,
        quality_repository,
        client,
        overview_client,
    )


def test_explicit_today_window_completes_as_empty_when_tiktok_is_not_available_yet() -> (
    None
):
    client = FakeClient()
    overview_client = NoDataOverviewClient()
    service, sync_repository, analytics_repository, _, _, _ = _service(
        client=client,
        overview_client=overview_client,
    )

    result = asyncio.run(
        service.sync(
            uuid4(),
            shop_id=uuid4(),
            resource_type="video",
            job_id="analytics-video-window:today-empty",
            attempt=1,
            max_attempts=5,
            window_start=datetime(2026, 8, 19, tzinfo=UTC),
            window_end=datetime(2026, 8, 20, tzinfo=UTC),
            currency="USD",
            account_type="ALL",
        )
    )

    assert result.status == "succeeded"
    assert client.calls == []
    assert analytics_repository.snapshot_calls == []
    assert sync_repository.failed == []
    assert sync_repository.completed == [
        {"committed_cursor": None, "update_cursor": False}
    ]
    assert sync_repository.pages[0]["latest_available_date"] == date(2026, 8, 17)


def test_first_sync_uses_a_bounded_30_day_window_and_commits_a_watermark() -> None:
    (
        service,
        sync_repository,
        analytics_repository,
        quality_repository,
        client,
        overview_client,
    ) = _service()

    result = asyncio.run(
        service.sync(
            uuid4(),
            shop_id=uuid4(),
            resource_type="video",
            job_id="analytics-sync:shop:video",
            attempt=1,
            max_attempts=5,
        )
    )

    assert result.status == "succeeded"
    created = sync_repository.created[0]
    assert created["start_cursor"] is None
    assert created["window_end"] - created["window_start"] == timedelta(days=30)
    assert (
        client.calls[0][2]["start_date_ge"]
        == created["window_start"].date().isoformat()
    )
    assert (
        sync_repository.completed[0]["committed_cursor"]
        == created["window_end"].isoformat()
    )
    assert [page["raw_payload_kind"] for page in sync_repository.pages] == [
        "video_overview",
        "video_page",
    ]
    assert analytics_repository.video_calls[0][1]["external_id_field"] == "videoId"
    stored_metadata = analytics_repository.video_calls[0][0][2][0].fields
    assert stored_metadata == {"videoId": "video-1", "title": "Video"}
    assert len(analytics_repository.performance_repository.calls) == 1
    stored_metrics = analytics_repository.performance_repository.calls[0][0][3][
        0
    ].fields
    assert stored_metrics["views"] == 308
    assert stored_metrics["gmvAmount"] == "12.34"
    assert len(analytics_repository.snapshot_calls[0][0][2]) == 1
    assert overview_client.calls[0][0] == "video"
    assert overview_client.calls[0][2]["currency"] == "USD"
    assert quality_repository.calls[0][1]["external_id_field"] == "videoId"


def test_successful_watermark_enables_only_the_incremental_window() -> None:
    watermark = (
        datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        - timedelta(days=1)
    ).isoformat()
    service, sync_repository, _, _, client, _ = _service(watermark)

    asyncio.run(
        service.sync(
            uuid4(),
            shop_id=uuid4(),
            resource_type="video",
            job_id="analytics-sync:shop:video",
            attempt=1,
            max_attempts=5,
        )
    )

    created = sync_repository.created[0]
    assert created["start_cursor"] == watermark
    assert created["window_end"] - created["window_start"] == timedelta(days=1)
    assert client.calls[0][0] == "video"


def test_invalid_committed_cursor_never_starts_an_unbounded_sync() -> None:
    service, sync_repository, _, _, _, _ = _service("untrusted-page-token")

    with pytest.raises(AnalyticsSyncWindowError, match="UTC ISO 8601"):
        asyncio.run(
            service.sync(
                uuid4(),
                shop_id=uuid4(),
                resource_type="video",
                job_id="analytics-sync:shop:video",
                attempt=1,
                max_attempts=5,
            )
        )

    assert sync_repository.created == []


def test_hourly_schedule_uses_an_hourly_watermark_and_platform_date_window() -> None:
    watermark = (
        datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
        - timedelta(hours=1)
    ).isoformat()
    service, sync_repository, _, _, client, _ = _service(
        watermark, schedule_mode="hourly"
    )

    asyncio.run(
        service.sync(
            uuid4(),
            shop_id=uuid4(),
            resource_type="video",
            job_id="analytics-sync:shop:video",
            attempt=1,
            max_attempts=5,
        )
    )

    created = sync_repository.created[0]
    assert created["window_end"] - created["window_start"] == timedelta(hours=1)
    assert (
        client.calls[0][2]["end_date_lt"]
        == (created["window_end"] + timedelta(days=1)).date().isoformat()
    )


def test_platform_dates_use_the_configured_shop_timezone() -> None:
    shop_timezone = ZoneInfo("America/Los_Angeles")
    utc_midnight = datetime(2026, 8, 17, tzinfo=UTC)

    start, _ = platform_dates(
        utc_midnight,
        utc_midnight + timedelta(days=1),
        shop_timezone,
        explicit_window=True,
        schedule_mode="daily",
    )

    assert start.isoformat() == "2026-08-16"


def test_initial_window_keeps_midnight_across_daylight_saving_transition() -> None:
    shop_timezone = ZoneInfo("America/Los_Angeles")
    first_day_after_dst = datetime(2026, 3, 15, 7, tzinfo=UTC)

    start = initial_window_start(first_day_after_dst, shop_timezone, 30)

    assert start == datetime(2026, 2, 13, 8, tzinfo=UTC)
    assert start.astimezone(shop_timezone).hour == 0


def test_explicit_video_window_uses_one_run_and_does_not_advance_cursor() -> None:
    watermark = "2026-07-31T00:00:00+00:00"
    service, sync_repository, analytics_repository, _, client, overview_client = (
        _service(watermark)
    )
    window_start = datetime(2026, 8, 1, tzinfo=UTC)
    window_end = datetime(2026, 8, 16, tzinfo=UTC)

    result = asyncio.run(
        service.sync(
            uuid4(),
            shop_id=uuid4(),
            resource_type="video",
            job_id="analytics-video-window:test",
            attempt=1,
            max_attempts=5,
            window_start=window_start,
            window_end=window_end,
            currency="USD",
            account_type="ALL",
        )
    )

    assert result.status == "succeeded"
    assert sync_repository.created[0]["start_cursor"] is None
    assert sync_repository.cursor_reads == 0
    assert sync_repository.completed == [
        {"committed_cursor": None, "update_cursor": False}
    ]
    assert client.calls[0][2]["start_date_ge"] == "2026-08-01"
    assert client.calls[0][2]["end_date_lt"] == "2026-08-16"
    assert overview_client.calls[0][2]["account_type"] == "ALL"
    performance_call = analytics_repository.performance_repository.calls[0]
    assert performance_call[0][2] == sync_repository.started[0]
    assert performance_call[1]["window_start"] == window_start
    assert performance_call[1]["window_end"] == window_end


class FailingSecondPageClient(FakeClient):
    async def iter_videos(self, access_token, **kwargs):
        async for page in super().iter_videos(access_token, **kwargs):
            yield page
        raise RuntimeError("second page failed")


class ExplicitLiveClient(FakeClient):
    async def iter_lives(self, access_token, **kwargs):
        self.calls.append(("live", access_token, kwargs))
        if kwargs["account_type"] != "AFFILIATE_ACCOUNTS":
            return
        yield TikTokAnalyticsPage(
            items=[
                TikTokAnalyticsItem(
                    fields={"liveId": "live-1", "gmvAmount": "42.50"},
                    source_status=None,
                    status=None,
                    source_updated_at=None,
                )
            ],
            next_page_token=None,
            platform_request_id="live-request-1",
            source_updated_at=None,
            raw_payload={
                "data": {"live_stream_sessions": [{"id": "live-1"}]},
                "request_id": "live-request-1",
            },
        )


def test_explicit_live_window_creates_audited_backfill_without_advancing_cursor() -> (
    None
):
    client = ExplicitLiveClient()
    service, sync_repository, analytics_repository, _, _, _ = _service(client=client)

    result = asyncio.run(
        service.sync(
            uuid4(),
            shop_id=uuid4(),
            resource_type="live",
            job_id="analytics-live-window:test",
            attempt=1,
            max_attempts=5,
            window_start=datetime(2026, 8, 1, tzinfo=UTC),
            window_end=datetime(2026, 8, 2, tzinfo=UTC),
            currency="USD",
        )
    )

    assert result.status == "succeeded"
    assert sync_repository.cursor_reads == 0
    assert sync_repository.completed == [
        {"committed_cursor": None, "update_cursor": False}
    ]
    assert analytics_repository.live_calls[0][1]["platform_request_id"] == (
        "live-request-1"
    )
    assert sync_repository.pages[-1]["raw_payload_kind"] == "live_page"


def test_failed_later_page_never_marks_partial_video_batch_readable() -> None:
    service, sync_repository, analytics_repository, _, _, _ = _service(
        client=FailingSecondPageClient()
    )

    result = asyncio.run(
        service.sync(
            uuid4(),
            shop_id=uuid4(),
            resource_type="video",
            job_id="analytics-video-window:test-failure",
            attempt=1,
            max_attempts=5,
            window_start=datetime(2026, 8, 1, tzinfo=UTC),
            window_end=datetime(2026, 8, 2, tzinfo=UTC),
        )
    )

    assert result.status == "failed"
    assert len(analytics_repository.performance_repository.calls) == 1
    assert sync_repository.completed == []
    assert len(sync_repository.failed) == 1
