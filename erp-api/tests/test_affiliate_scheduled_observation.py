import asyncio
from datetime import UTC, date, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from erp_api.services.affiliate_center_contract import AffiliateCenterResource
from erp_api.workers import affiliate_creator_jobs, affiliate_video_jobs


@pytest.mark.parametrize(
    ("module", "entrypoint", "resource"),
    [
        (
            affiliate_creator_jobs,
            "enqueue_scheduled_affiliate_creator_syncs",
            "creators",
        ),
        (affiliate_video_jobs, "enqueue_scheduled_affiliate_video_syncs", "videos"),
    ],
)
def test_schedule_uses_fresh_tk_observation_not_copied_health_date(
    monkeypatch, module, entrypoint, resource
):
    tenant_id, shop_id = uuid4(), uuid4()
    observed = date(2026, 10, 3)
    calls = []

    class HealthRepository:
        def __init__(self, redis):
            assert redis == "redis"

        async def get(self, _tenant_id, _shop_id):
            return SimpleNamespace(
                state="online",
                session_available=True,
                latest_available_dates={resource: date(2026, 10, 1)},
                recovered_at=None,
            )

        async def observed_date_for(self, _tenant_id, _shop_id, actual_resource):
            calls.append(actual_resource)
            return observed

    class Schedule:
        def __init__(self, database, **kwargs):
            assert database == "database"
            self.provider = kwargs["availability_provider"]

        async def enqueue_due(self, _now):
            return await self.provider(
                tenant_id, shop_id, AffiliateCenterResource(resource)
            )

    monkeypatch.setattr(module, "AffiliateCaptureHealthRepository", HealthRepository)
    scheduler_name = (
        "AffiliateCreatorScheduleService"
        if resource == "creators"
        else "AffiliateVideoScheduleService"
    )
    monkeypatch.setattr(module, scheduler_name, Schedule)
    monkeypatch.setattr(
        module,
        "get_settings",
        lambda: SimpleNamespace(
            tiktok_affiliate_creator_schedule_max_attempts=3,
            tiktok_affiliate_creator_retry_minutes=10,
            tiktok_affiliate_video_schedule_max_attempts=3,
            tiktok_affiliate_video_retry_minutes=10,
        ),
    )
    monkeypatch.setattr(module, "_now", lambda _ctx: datetime(2026, 10, 5, tzinfo=UTC))
    result = asyncio.run(
        getattr(module, entrypoint)({"redis": "redis", "database": "database"})
    )
    assert result == observed
    assert calls == [resource]
