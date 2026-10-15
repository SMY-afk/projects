import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from erp_api.models.affiliate_creator import AffiliateCreatorReport
from erp_api.models.analytics_sync import AnalyticsSyncCursor, AnalyticsSyncRun
from erp_api.services.affiliate_creator_regression_guard import (
    mark_creator_count_regression_partial,
)
from erp_api.services.affiliate_creator_report_completion import (
    AffiliateCreatorReportCompletion,
)
from erp_api.services.analytics_sync_repository import AnalyticsSyncRepository


class FakeDatabase:
    def __init__(self, session) -> None:
        self._session = session

    async def session(self, tenant_id):
        yield self._session


class FakeSession:
    def __init__(self, run, report, previous_report) -> None:
        self.run = run
        self.report = report
        self.previous_report = previous_report
        self.report_reads = 0
        self.cursor = None
        self.commits = 0

    async def get(self, model, value):
        if model is AnalyticsSyncRun and value == self.run.id:
            return self.run
        return None

    async def scalar(self, statement):
        entity = statement.column_descriptions[0].get("entity")
        if entity is AffiliateCreatorReport:
            self.report_reads += 1
            return self.report if self.report_reads == 1 else self.previous_report
        return self.cursor

    async def execute(self, statement):
        return None

    def add(self, value) -> None:
        if isinstance(value, AnalyticsSyncCursor):
            self.cursor = value

    async def commit(self) -> None:
        self.commits += 1


def test_creator_count_regression_is_partial_and_keeps_complete_report() -> None:
    tenant_id, shop_id = uuid4(), uuid4()
    run = AnalyticsSyncRun(
        id=uuid4(),
        tenant_id=tenant_id,
        shop_id=shop_id,
        resource_type="affiliate_creator",
        job_id="affiliate-creator-regression",
        status="running",
        attempt_count=1,
        window_start=datetime(2026, 8, 23, tzinfo=UTC),
        window_end=datetime(2026, 8, 30, tzinfo=UTC),
        fetched_count=500,
        persisted_count=500,
    )
    report = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        shop_id=shop_id,
        query_fingerprint="creator-query",
        status="running",
        expected_total=None,
        pages_fetched=0,
        records_received=0,
        records_unique=0,
        duplicate_count=0,
        completeness_reason=None,
    )
    previous_report = SimpleNamespace(id=uuid4(), status="complete", records_unique=595)
    session = FakeSession(run, report, previous_report)
    repository = AnalyticsSyncRepository(FakeDatabase(session))

    result = asyncio.run(
        repository.complete_run(
            tenant_id,
            run.id,
            creator_report_id=report.id,
            report_completion=AffiliateCreatorReportCompletion(
                expected_total=500,
                pages_fetched=1,
                records_received=500,
                records_unique=500,
                duplicate_count=0,
                completeness_reason="complete",
            ),
        )
    )

    assert result.status == "partial"
    assert run.error_category == "total_count_mismatch"
    assert report.status == "partial"
    assert report.expected_total == 595
    assert report.records_unique == 500
    assert report.completeness_reason == "total_count_mismatch"
    assert previous_report.status == "complete"
    assert previous_report.records_unique == 595
    assert session.cursor is None
    assert session.commits == 1


def test_compass_snapshot_does_not_compare_against_a_legacy_provider() -> None:
    tenant_id, shop_id = uuid4(), uuid4()
    run = SimpleNamespace(shop_id=shop_id)
    report = SimpleNamespace(
        id=uuid4(),
        query_fingerprint="creator-query",
        source_metadata={"provider": "tiktok_compass_creator_xlsx"},
    )
    previous_report = SimpleNamespace(
        id=uuid4(),
        records_unique=595,
        source_metadata={"provider": "legacy_video_aggregation"},
    )
    session = FakeSession(run, report, previous_report)
    session.report_reads = 1
    completion = AffiliateCreatorReportCompletion(
        expected_total=315,
        pages_fetched=1,
        records_received=315,
        records_unique=315,
        duplicate_count=0,
        completeness_reason="complete",
    )

    guarded = asyncio.run(
        mark_creator_count_regression_partial(
            session,
            tenant_id,
            run,
            report,
            completion,
            completed_at=datetime.now(UTC),
        )
    )

    assert guarded is False
