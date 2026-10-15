import asyncio
import inspect
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from erp_api.services.affiliate_center_contract import AffiliateCenterResource
from erp_api.services.affiliate_creator_schedule import (
    AffiliateCreatorScheduleService,
    next_scheduled_attempt,
)
from erp_api.services.affiliate_schedule_queries import (
    ScheduledShop,
    daily_capture_window_open,
    daily_capture_window_start,
    daily_collection_window_open,
    daily_retry_window_open,
    latest_due_capture_window_start,
    latest_due_schedule_date,
    previous_shop_day,
    scheduled_affiliate_queries,
    scheduled_creator_query,
    scheduled_query_job_base,
)
from erp_api.workers import settings as worker_settings
from erp_api.workers.affiliate_creator_jobs import (
    enqueue_scheduled_affiliate_creator_syncs,
)


def _run(status: str, finished_at: datetime | None = None):
    return SimpleNamespace(
        status=status,
        started_at=datetime(2026, 8, 27, tzinfo=UTC),
        finished_at=finished_at,
    )


def test_daily_batch_becomes_due_at_2330_beijing() -> None:
    assert (
        latest_due_schedule_date(datetime(2026, 8, 27, 15, 29, tzinfo=UTC)).isoformat()
        == "2026-08-26"
    )
    assert (
        latest_due_schedule_date(datetime(2026, 8, 27, 15, 30, tzinfo=UTC)).isoformat()
        == "2026-08-27"
    )


def test_daily_capture_targets_the_previous_shop_local_day() -> None:
    now = datetime(2026, 9, 14, 15, 30, tzinfo=UTC)

    assert previous_shop_day(now, "America/Los_Angeles").isoformat() == "2026-09-13"


def test_daily_capture_window_is_limited_to_fifteen_minutes() -> None:
    assert not daily_capture_window_open(datetime(2026, 9, 14, 15, 29, 59, tzinfo=UTC))
    assert daily_capture_window_open(datetime(2026, 9, 14, 15, 30, tzinfo=UTC))
    assert daily_capture_window_open(datetime(2026, 9, 14, 15, 44, 59, tzinfo=UTC))
    assert not daily_capture_window_open(datetime(2026, 9, 14, 15, 45, tzinfo=UTC))


def test_daily_retry_window_stays_open_until_0800_beijing() -> None:
    assert not daily_retry_window_open(datetime(2026, 9, 14, 15, 29, tzinfo=UTC))
    assert daily_retry_window_open(datetime(2026, 9, 14, 15, 30, tzinfo=UTC))
    assert daily_retry_window_open(datetime(2026, 9, 14, 23, 59, tzinfo=UTC))
    assert not daily_retry_window_open(datetime(2026, 9, 15, 0, 0, tzinfo=UTC))


def test_daily_collection_waits_for_staggered_availability_probes() -> None:
    assert not daily_collection_window_open(
        datetime(2026, 9, 14, 15, 49, 59, tzinfo=UTC)
    )
    assert daily_collection_window_open(datetime(2026, 9, 14, 15, 50, tzinfo=UTC))
    assert daily_collection_window_open(datetime(2026, 9, 14, 23, 59, tzinfo=UTC))
    assert not daily_collection_window_open(datetime(2026, 9, 15, 0, 0, tzinfo=UTC))


def test_daily_capture_window_start_is_returned_in_utc() -> None:
    assert daily_capture_window_start(
        datetime(2026, 9, 14, 15, 41, tzinfo=UTC)
    ) == datetime(2026, 9, 14, 15, 30, tzinfo=UTC)


def test_latest_due_capture_window_start_uses_previous_night_during_daytime() -> None:
    assert latest_due_capture_window_start(
        datetime(2026, 9, 17, 5, 30, tzinfo=UTC)
    ) == datetime(2026, 9, 16, 15, 30, tzinfo=UTC)


def test_creator_window_uses_the_latest_date_observed_in_tiktok() -> None:
    shop = ScheduledShop(uuid4(), uuid4(), "America/Los_Angeles", "USD")
    query = scheduled_creator_query(
        shop,
        date(2026, 8, 29),
    )

    assert query.window_start.isoformat() == "2026-08-29"
    assert query.window_end.isoformat() == "2026-08-29"


def test_creator_scheduler_covers_two_calendar_months_in_bounded_chunks() -> None:
    shop = ScheduledShop(uuid4(), uuid4(), "America/Los_Angeles", "USD")

    queries = scheduled_affiliate_queries(
        shop,
        date(2026, 8, 29),
        resource=AffiliateCenterResource.CREATORS,
    )

    assert [(q.window_start, q.window_end) for q in queries] == [
        (date(2026, 6, 29), date(2026, 7, 28)),
        (date(2026, 7, 29), date(2026, 8, 27)),
        (date(2026, 8, 28), date(2026, 8, 29)),
    ]


def test_video_scheduler_covers_the_same_two_month_window() -> None:
    shop = ScheduledShop(uuid4(), uuid4(), "America/Los_Angeles", "USD")

    queries = scheduled_affiliate_queries(
        shop,
        date(2026, 8, 29),
        resource=AffiliateCenterResource.VIDEOS,
    )

    assert len(queries) == 3
    assert queries[0].window_start == date(2026, 6, 29)
    assert queries[-1].window_end == date(2026, 8, 29)


def test_exact_range_uses_a_distinct_schedule_job_identity() -> None:
    shop = ScheduledShop(uuid4(), uuid4(), "America/Los_Angeles", "USD")
    first, _, last = scheduled_affiliate_queries(
        shop,
        date(2026, 8, 29),
        resource=AffiliateCenterResource.CREATORS,
    )

    assert scheduled_query_job_base(first, date(2026, 8, 30), date(2026, 8, 29)) == (
        f"affiliate-schedule:20260830:20260829:{shop.shop_id}:creator:20260629-20260728"
    )
    assert scheduled_query_job_base(last, date(2026, 8, 30), date(2026, 8, 29)) == (
        f"affiliate-schedule:20260830:20260829:{shop.shop_id}:creator:20260828-20260829"
    )


def test_creator_scheduler_uses_each_shops_verified_cutoff() -> None:
    tenant_id = uuid4()
    names = [
        "fanfu toy tool",
        "Akeleo-Drive",
        "Akeleo Fun Toys",
        "NEOPUP",
        "Akeleo Toys",
    ]
    shops = [
        ScheduledShop(tenant_id, uuid4(), "America/Los_Angeles", "USD", name)
        for name in names
    ]
    available = {
        shop.shop_id: date(2026, 9, 18) if index == 0 else date(2026, 9, 17)
        for index, shop in enumerate(shops)
    }
    captured = []

    async def availability(tenant_id, shop_id, resource):
        return available.get(shop_id)

    async def enqueue(shop, query, job_base, attempt):
        captured.append((shop, query, job_base, attempt))
        return True

    service = AffiliateCreatorScheduleService(
        None,
        availability_provider=availability,
        enqueuer=enqueue,
    )
    service._active_shops = lambda: asyncio.sleep(0, result=shops)
    service._next_attempt = lambda *args: asyncio.sleep(0, result=1)

    queued = asyncio.run(service.enqueue_due(datetime(2026, 9, 19, 15, 50, tzinfo=UTC)))

    assert queued == 15
    by_shop = {shop.shop_id: [] for shop in shops}
    for shop, query, _, _ in captured:
        by_shop[shop.shop_id].append(query)
    assert by_shop[shops[0].shop_id][-1].window_end == date(2026, 9, 18)
    assert all(
        by_shop[shop.shop_id][-1].window_end == date(2026, 9, 17) for shop in shops[1:]
    )


def test_creator_scheduler_retries_only_shops_with_available_dates() -> None:
    tenant_id = uuid4()
    names = [
        "fanfu toy tool",
        "Akeleo-Drive",
        "Akeleo Fun Toys",
        "NEOPUP",
        "Akeleo Toys",
    ]
    shops = [
        ScheduledShop(tenant_id, uuid4(), "America/Los_Angeles", "USD", name)
        for name in names
    ]
    captured = []

    async def availability(tenant_id, shop_id, resource):
        return None if shop_id == shops[-1].shop_id else date(2026, 9, 17)

    async def enqueue(*args):
        captured.append(args)
        return True

    service = AffiliateCreatorScheduleService(
        None,
        availability_provider=availability,
        enqueuer=enqueue,
    )
    service._active_shops = lambda: asyncio.sleep(0, result=shops)
    service._next_attempt = lambda *args: asyncio.sleep(0, result=1)

    queued = asyncio.run(service.enqueue_due(datetime(2026, 9, 19, 15, 50, tzinfo=UTC)))

    assert queued == 12
    assert {item[0].shop_id for item in captured} == {
        shop.shop_id for shop in shops[:-1]
    }


def test_failed_batch_retries_after_delay_without_overriding_success() -> None:
    now = datetime(2026, 8, 27, 2, tzinfo=UTC)
    failed = _run("failed", now - timedelta(minutes=11))

    assert (
        next_scheduled_attempt(
            [], [], now=now, max_attempts=3, retry_delay=timedelta(minutes=10)
        )
        == 1
    )
    assert (
        next_scheduled_attempt(
            [], [failed], now=now, max_attempts=3, retry_delay=timedelta(minutes=10)
        )
        == 2
    )
    assert (
        next_scheduled_attempt(
            [_run("succeeded")],
            [failed],
            now=now,
            max_attempts=3,
            retry_delay=timedelta(minutes=10),
        )
        is None
    )
    assert (
        next_scheduled_attempt(
            [],
            [failed, failed, failed],
            now=now,
            max_attempts=3,
            retry_delay=timedelta(minutes=10),
        )
        is None
    )


def test_health_recovery_allows_one_more_attempt_after_retry_limit() -> None:
    now = datetime(2026, 8, 27, 2, tzinfo=UTC)
    failures = [
        _run("failed", now - timedelta(minutes=30)),
        _run("failed", now - timedelta(minutes=20)),
        _run("failed", now - timedelta(minutes=11)),
    ]

    assert (
        next_scheduled_attempt(
            [],
            failures,
            now=now,
            max_attempts=3,
            retry_delay=timedelta(minutes=10),
            recovered_at=now - timedelta(minutes=5),
        )
        == 4
    )

    failures.insert(0, _run("failed", now - timedelta(minutes=1)))
    assert (
        next_scheduled_attempt(
            [],
            failures,
            now=now,
            max_attempts=3,
            retry_delay=timedelta(minutes=10),
            recovered_at=now - timedelta(minutes=5),
        )
        is None
    )


def test_worker_rechecks_failed_shops_every_ten_minutes_in_retry_window() -> None:
    startup_source = inspect.getsource(worker_settings.startup)
    cron_source = inspect.getsource(worker_settings.WorkerSettings)

    assert "await enqueue_scheduled_affiliate_creator_syncs(ctx)" not in startup_source
    assert (
        enqueue_scheduled_affiliate_creator_syncs
        in worker_settings.WorkerSettings.functions
    )
    assert (
        "cron(enqueue_scheduled_affiliate_creator_syncs, minute=set(range(0, 60, 10)))"
        in cron_source
    )
