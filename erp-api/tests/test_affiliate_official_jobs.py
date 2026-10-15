from datetime import date
from types import SimpleNamespace
from uuid import uuid4

import pytest
from arq import Retry

from erp_api.services.affiliate_video_page_query import _run_dict
from erp_api.services.compass_export_rate_gate import CompassExportDeferred
from erp_api.services.tiktok_transport import TikTokApiError, TikTokRateLimitError
from erp_api.workers.affiliate_official_jobs import (
    _rolling_windows,
    sync_official_affiliate_job,
)
from erp_api.workers.settings import WorkerSettings


def test_official_daily_sync_keeps_latest_sixty_days_queryable() -> None:
    assert _rolling_windows(date(2026, 8, 31)) == [
        (date(2026, 8, 25), date(2026, 8, 31)),
        (date(2026, 7, 3), date(2026, 8, 1)),
        (date(2026, 8, 2), date(2026, 8, 31)),
    ]


def test_official_affiliate_video_snapshot_reports_its_real_source() -> None:
    run = SimpleNamespace(
        id="run-1",
        resource_type="affiliate_video",
        job_id="official-affiliate-schedule:shop:videos:20260825:20260831",
        status="succeeded",
        fetched_count=1,
        persisted_count=1,
        started_at=None,
        finished_at=None,
        last_source_updated_at=None,
        error_category=None,
        error_summary=None,
    )

    assert _run_dict(run)["sourceKind"] == "official_api"


def test_official_compass_job_has_enough_attempts_for_serial_hourly_exports() -> None:
    registered = next(
        function
        for function in WorkerSettings.functions
        if getattr(function, "name", None) == "sync_official_affiliate_job"
    )

    assert registered.max_tries == 24


@pytest.mark.asyncio
async def test_official_compass_rate_limit_retries_later() -> None:
    class Service:
        async def sync(self, tenant_id, query, *, job_id):
            raise TikTokRateLimitError(retry_after_seconds=None)

    with pytest.raises(Retry) as caught:
        await sync_official_affiliate_job(
            {"official_affiliate_sync_service": Service()},
            str(uuid4()),
            str(uuid4()),
            "creators",
            "2026-08-26",
            "2026-09-01",
            "America/Los_Angeles",
            "USD",
            "job-1",
        )

    assert caught.value.defer_score == 3_600_000


@pytest.mark.asyncio
async def test_official_compass_task_quota_retries_later() -> None:
    class Service:
        async def sync(self, tenant_id, query, *, job_id):
            raise TikTokApiError("throttled", code="13017003", status_code=502)

    with pytest.raises(Retry) as caught:
        await sync_official_affiliate_job(
            {"official_affiliate_sync_service": Service()},
            str(uuid4()),
            str(uuid4()),
            "creators",
            "2026-08-26",
            "2026-09-01",
            "America/Los_Angeles",
            "USD",
            "job-2",
        )

    assert caught.value.defer_score == 3_600_000


@pytest.mark.asyncio
async def test_official_compass_local_gate_preserves_remaining_delay() -> None:
    class Service:
        async def sync(self, tenant_id, query, *, job_id):
            raise CompassExportDeferred(1_234)

    with pytest.raises(Retry) as caught:
        await sync_official_affiliate_job(
            {"official_affiliate_sync_service": Service()},
            str(uuid4()),
            str(uuid4()),
            "creators",
            "2026-08-26",
            "2026-09-01",
            "America/Los_Angeles",
            "USD",
            "job-gated",
        )

    assert caught.value.defer_score == 1_234_000
