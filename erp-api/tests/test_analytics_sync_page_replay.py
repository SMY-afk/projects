import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from erp_api.models.analytics_sync import AnalyticsRawPayload, AnalyticsSyncRun
from erp_api.services.analytics_sync_repository import AnalyticsSyncRepository


class FakeDatabase:
    def __init__(self, session) -> None:
        self.session_value = session

    async def session(self, tenant_id):
        yield self.session_value


class FakeSession:
    def __init__(self, run) -> None:
        self.run = run
        self.added = []
        self.commits = 0

    async def get(self, model, value):
        return self.run if model is AnalyticsSyncRun and value == self.run.id else None

    async def scalar(self, statement):
        entity = statement.column_descriptions[0].get("entity")
        return uuid4() if entity is AnalyticsRawPayload else None

    async def execute(self, statement):
        return SimpleNamespace()

    def add(self, value) -> None:
        self.added.append(value)

    async def commit(self) -> None:
        self.commits += 1


def _run(tenant_id, shop_id) -> AnalyticsSyncRun:
    return AnalyticsSyncRun(
        id=uuid4(),
        tenant_id=tenant_id,
        shop_id=shop_id,
        resource_type="affiliate_creator",
        job_id="affiliate-page:test",
        status="running",
        attempt_count=1,
        window_start=datetime(2026, 8, 1, tzinfo=UTC),
        window_end=datetime(2026, 8, 2, tzinfo=UTC),
        fetched_count=0,
        persisted_count=0,
    )


def test_recorded_page_replay_does_not_advance_page_audit() -> None:
    tenant_id, shop_id = uuid4(), uuid4()
    run = _run(tenant_id, shop_id)
    session = FakeSession(run)
    repository = AnalyticsSyncRepository(FakeDatabase(session))

    asyncio.run(
        repository.record_page(
            tenant_id,
            run.id,
            next_cursor="page:2",
            fetched_count=10,
            persisted_count=10,
            platform_request_id="request-1",
            source_updated_at=None,
            raw_payload_kind="affiliate_creator_page",
            raw_payload={"data": {}},
            page_number=1,
        )
    )

    assert (run.fetched_count, run.persisted_count, run.recovery_cursor) == (0, 0, None)
    assert session.added == []
    assert session.commits == 0


def test_has_recorded_page_accepts_request_or_page_identity() -> None:
    tenant_id, shop_id = uuid4(), uuid4()
    run = _run(tenant_id, shop_id)
    repository = AnalyticsSyncRepository(FakeDatabase(FakeSession(run)))

    recorded = asyncio.run(
        repository.has_recorded_page(
            tenant_id,
            shop_id,
            run.id,
            platform_request_id="request-1",
            raw_payload_kind="affiliate_creator_page",
            page_number=1,
        )
    )

    assert recorded is True
