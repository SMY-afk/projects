import asyncio
from datetime import UTC, date, datetime
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from erp_api.models.analytics_sync import AnalyticsSyncRun
from erp_api.services.affiliate_capture_intent_repository import (
    AffiliateCaptureIntentRepository,
)
from erp_api.services.affiliate_center_contract import (
    AffiliateCenterQuery,
    AffiliateCenterResource,
)


class FakeDatabase:
    def __init__(self, session) -> None:
        self.session_value = session

    async def session(self, tenant_id):
        yield self.session_value


class FakeSession:
    def __init__(self, *, scalars=None, run=None) -> None:
        self.scalars = list(scalars or [])
        self.run = run
        self.added = []
        self.executed = []
        self.commits = 0

    async def scalar(self, statement):
        self.executed.append(statement)
        return self.scalars.pop(0) if self.scalars else None

    async def execute(self, statement):
        self.executed.append(statement)

    def add(self, value) -> None:
        if value.id is None:
            value.id = uuid4()
        self.added.append(value)

    async def flush(self) -> None:
        return None

    async def get(self, model, value):
        if model is AnalyticsSyncRun and self.run is not None and self.run.id == value:
            return self.run
        return None

    async def commit(self) -> None:
        self.commits += 1


class EmptyQueryResult:
    def one_or_none(self):
        return None


class NextQueuedSession(FakeSession):
    async def execute(self, statement):
        self.executed.append(statement)
        return EmptyQueryResult()


def _query() -> AffiliateCenterQuery:
    return AffiliateCenterQuery(
        resource=AffiliateCenterResource.CREATORS,
        shop_id=uuid4(),
        window_start=date(2026, 8, 1),
        window_end=date(2026, 8, 7),
        shop_timezone="America/Los_Angeles",
        currency="USD",
        filters={},
    )


def _run(query, *, status="queued") -> AnalyticsSyncRun:
    start, end = query.utc_window()
    return AnalyticsSyncRun(
        id=uuid4(),
        tenant_id=uuid4(),
        shop_id=query.shop_id,
        resource_type="affiliate_creator",
        job_id="affiliate-intent:test",
        status=status,
        attempt_count=0,
        window_start=start,
        window_end=end,
        currency=query.currency,
        account_type="AFFILIATE_ACCOUNTS",
        fetched_count=0,
        persisted_count=0,
    )


def test_enqueue_creates_a_queued_browser_intent() -> None:
    query = _query()
    session = FakeSession(scalars=[None])
    repository = AffiliateCaptureIntentRepository(FakeDatabase(session))

    receipts = asyncio.run(repository.enqueue(uuid4(), [query]))

    run = session.added[0]
    assert run.status == "queued"
    assert run.resource_type == "affiliate_creator"
    assert run.job_id.startswith("affiliate-intent:")
    assert receipts[0].run_id == run.id
    assert receipts[0].existing is False
    assert session.commits == 1


def test_enqueue_reuses_the_same_active_query_intent() -> None:
    query = _query()
    existing = _run(query)
    session = FakeSession(scalars=[existing])
    repository = AffiliateCaptureIntentRepository(FakeDatabase(session))

    receipts = asyncio.run(repository.enqueue(existing.tenant_id, [query]))

    assert receipts[0].run_id == existing.id
    assert receipts[0].existing is True
    assert session.added == []


def test_long_window_retry_can_reuse_a_succeeded_chunk() -> None:
    query = _query().with_resource(AffiliateCenterResource.VIDEOS)
    existing = _run(query, status="succeeded")
    existing.resource_type = "affiliate_video"
    session = FakeSession(scalars=[existing])
    repository = AffiliateCaptureIntentRepository(FakeDatabase(session))

    receipts = asyncio.run(
        repository.enqueue(existing.tenant_id, [query], reuse_succeeded=True)
    )

    assert receipts[0].run_id == existing.id
    assert receipts[0].status == "succeeded"
    assert receipts[0].existing is True
    assert session.added == []


def test_next_queued_prioritizes_the_newest_missing_window() -> None:
    session = NextQueuedSession()
    repository = AffiliateCaptureIntentRepository(FakeDatabase(session))

    result = asyncio.run(
        repository.next_queued(uuid4(), frozenset({"9121478993551097445"}))
    )

    assert result is None
    sql = str(
        session.executed[0].compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert (
        "ORDER BY analytics_sync_runs.window_start DESC, "
        "analytics_sync_runs.started_at ASC" in sql
    )
    assert "analytics_sync_runs.job_id NOT LIKE" in sql
    assert "official-affiliate" in sql


def test_next_queued_allows_manual_intents_outside_daily_window() -> None:
    session = NextQueuedSession()
    repository = AffiliateCaptureIntentRepository(FakeDatabase(session))

    asyncio.run(repository.next_queued(uuid4(), frozenset({"shop"})))

    sql = str(
        session.executed[0].compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "analytics_sync_runs.job_id LIKE 'affiliate-schedule:" not in sql


def test_claim_is_atomic_and_unstarted_failure_is_explicit() -> None:
    query = _query()
    run = _run(query)
    claim_session = FakeSession(scalars=[run.id])
    claimed = asyncio.run(
        AffiliateCaptureIntentRepository(FakeDatabase(claim_session)).claim_intent(
            run.tenant_id, run.id
        )
    )
    assert claimed is True
    assert claim_session.commits == 1

    fail_session = FakeSession(run=run)
    asyncio.run(
        AffiliateCaptureIntentRepository(FakeDatabase(fail_session)).fail_intent(
            run.tenant_id, run.id, "target_page_missing"
        )
    )
    assert run.status == "failed"
    assert run.error_category == "target_page_missing"
    assert "not open" in run.error_summary
    assert run.finished_at >= datetime(2026, 8, 1, tzinfo=UTC)


def test_creator_probe_structure_failure_has_a_safe_stage_summary() -> None:
    query = _query()
    run = _run(query)
    session = FakeSession(run=run)

    asyncio.run(
        AffiliateCaptureIntentRepository(FakeDatabase(session)).fail_intent(
            run.tenant_id, run.id, "creator_probe_structure_changed"
        )
    )

    assert run.status == "failed"
    assert run.error_category == "creator_probe_structure_changed"
    assert run.error_summary == "The TikTok creator list probe payload changed."


def test_captcha_deferral_requeues_a_running_intent() -> None:
    query = _query()
    run = _run(query, status="running")
    run.error_category = "captcha"
    run.error_summary = "stale"
    run.finished_at = datetime.now(UTC)
    session = FakeSession(run=run)

    asyncio.run(
        AffiliateCaptureIntentRepository(FakeDatabase(session)).defer_intent(
            run.tenant_id,
            run.id,
        )
    )

    assert run.status == "queued"
    assert run.error_category is None
    assert run.error_summary is None
    assert run.finished_at is None
    assert session.commits == 1
