import asyncio
import inspect
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from erp_api.services.affiliate_schedule_queries import ScheduledShop
from erp_api.services.affiliate_video_schedule import (
    AffiliateVideoScheduleService,
    scheduled_video_job_base,
    scheduled_video_query,
)
from erp_api.workers import settings as worker_settings
from erp_api.workers.affiliate_video_jobs import (
    enqueue_scheduled_affiliate_video_syncs,
)


def test_video_window_uses_the_latest_date_observed_in_tiktok() -> None:
    shop = ScheduledShop(uuid4(), uuid4(), "America/Los_Angeles", "USD")

    query = scheduled_video_query(
        shop,
        date(2026, 8, 29),
    )

    assert query.resource.value == "videos"
    assert query.window_start.isoformat() == "2026-08-29"
    assert query.window_end.isoformat() == "2026-08-29"


def test_video_schedule_uses_a_daily_shop_scoped_job_identity() -> None:
    shop_id = uuid4()

    assert (
        scheduled_video_job_base(datetime(2026, 8, 27, tzinfo=UTC).date(), shop_id)
        == f"affiliate-schedule:20260827:{shop_id}:video"
    )


def test_worker_runs_video_catch_up_once_daily_without_startup_collection() -> None:
    startup_source = inspect.getsource(worker_settings.startup)
    cron_source = inspect.getsource(worker_settings.WorkerSettings)

    assert "await enqueue_scheduled_affiliate_video_syncs(ctx)" not in startup_source
    assert (
        enqueue_scheduled_affiliate_video_syncs
        in worker_settings.WorkerSettings.functions
    )
    assert "enqueue_scheduled_affiliate_video_syncs," in cron_source
    assert (
        "cron(enqueue_scheduled_affiliate_video_syncs, minute=set(range(0, 60, 10)))"
        in cron_source
    )


def test_video_scheduler_reuses_retry_policy_without_browser_credentials() -> None:
    source = inspect.getsource(enqueue_scheduled_affiliate_video_syncs)

    assert 'ctx["database"]' in source
    assert "analytics_sync_service" not in source
    assert "cdp" not in source.casefold()
    assert "cookie" not in source.casefold()


class FakeScheduleSession:
    def __init__(self, scheduled_runs) -> None:
        self.results = [[], scheduled_runs]

    async def scalars(self, statement):
        return SimpleNamespace(all=lambda: self.results.pop(0))

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None


class FakeScheduleDatabase:
    def __init__(self, scheduled_runs) -> None:
        self.session = FakeScheduleSession(scheduled_runs)

    def system_session_factory(self):
        return self.session


def test_video_scheduler_uses_browser_recovery_to_unlock_catch_up() -> None:
    now = datetime(2026, 8, 28, 2, tzinfo=UTC)
    failures = [
        SimpleNamespace(
            status="failed",
            started_at=now - timedelta(minutes=10 + index * 10),
            finished_at=now - timedelta(minutes=10 + index * 10),
        )
        for index in range(3)
    ]
    recovered_at = now - timedelta(minutes=5)
    shop = ScheduledShop(uuid4(), uuid4(), "America/Los_Angeles", "USD")
    service = AffiliateVideoScheduleService(
        FakeScheduleDatabase(failures),
        recovery_provider=lambda tenant_id, shop_id: asyncio.sleep(
            0, result=recovered_at
        ),
    )

    attempt = asyncio.run(
        service._next_attempt(
            shop,
            scheduled_video_query(shop, date(2026, 8, 29)),
            scheduled_video_job_base(now.date(), shop.shop_id),
            now,
        )
    )

    assert attempt == 4
