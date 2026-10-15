from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from erp_api.workers import affiliate_live_observation as observation
from scripts.daily_valid_creator_online import MAX_EVIDENCE_AGE


@pytest.mark.asyncio
async def test_completed_affiliate_live_publishes_overview_date(monkeypatch):
    tenant_id, shop_id, run_id = uuid4(), uuid4(), uuid4()
    recorded = []

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def scalar(self, statement):
            assert "AFFILIATE_ACCOUNTS" in str(
                statement.compile(compile_kwargs={"literal_binds": True})
            )
            return date(2026, 10, 3)

    class Health:
        def __init__(self, redis):
            assert redis is sentinel

        async def record_observation(self, *args):
            recorded.append(args)

    sentinel = object()
    monkeypatch.setattr(observation, "AffiliateCaptureHealthRepository", Health)
    result = SimpleNamespace(
        run_id=run_id,
        shop_id=shop_id,
        resource_type="live",
        status="succeeded",
        fetched_count=10,
        persisted_count=10,
    )
    await observation.record_completed_live_date(
        {
            "database": SimpleNamespace(system_session_factory=Session),
            "redis": sentinel,
        },
        tenant_id,
        result,
    )
    assert recorded == [(tenant_id, shop_id, "liveAccounts", date(2026, 10, 3))]


@pytest.mark.asyncio
async def test_partial_live_result_does_not_publish_date():
    result = SimpleNamespace(
        resource_type="live",
        status="succeeded",
        fetched_count=10,
        persisted_count=9,
    )
    await observation.record_completed_live_date({"redis": object()}, uuid4(), result)


@pytest.mark.asyncio
async def test_recent_live_overview_is_fresh_and_non_regressing():
    now = datetime(2026, 10, 6, 3, tzinfo=UTC)

    class Rows:
        def __init__(self, row):
            self.row = row

        def one_or_none(self):
            return self.row

    class Session:
        def __init__(self, latest, row):
            self.latest = latest
            self.row = row

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def scalar(self, _statement):
            return self.latest

        async def execute(self, _statement):
            return Rows(self.row)

    tenant_id, shop_id = uuid4(), uuid4()
    recent = (date(2026, 10, 4), now - timedelta(minutes=5))
    database = SimpleNamespace(
        system_session_factory=lambda: Session(recent[0], recent)
    )
    assert (
        await observation.latest_recent_live_observation(
            database, tenant_id, shop_id, now=now
        )
        == recent
    )
    regressed = SimpleNamespace(
        system_session_factory=lambda: Session(
            date(2026, 10, 4), (date(2026, 10, 3), now)
        )
    )
    assert (
        await observation.latest_recent_live_observation(
            regressed, tenant_id, shop_id, now=now
        )
        is None
    )


@pytest.mark.asyncio
async def test_live_overview_uses_same_six_hour_window_as_online_evidence():
    now = datetime(2026, 10, 6, 3, tzinfo=UTC)
    observed = now - timedelta(hours=1)

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def scalar(self, _statement):
            return date(2026, 10, 4)

        async def execute(self, statement):
            query = str(statement.compile(compile_kwargs={"literal_binds": True}))
            assert (now - MAX_EVIDENCE_AGE).strftime("%Y-%m-%d %H:%M:%S") in query
            return SimpleNamespace(one_or_none=lambda: (date(2026, 10, 4), observed))

    database = SimpleNamespace(system_session_factory=Session)
    assert await observation.latest_recent_live_observation(
        database, uuid4(), uuid4(), now=now
    ) == (date(2026, 10, 4), observed)
