import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from erp_api.models.affiliate_creator import AffiliateCreatorReport
from erp_api.models.analytics_sync import AnalyticsSyncRun
from erp_api.services.affiliate_creator_report_completion import (
    AffiliateCreatorReportPartial,
)
from erp_api.services.analytics_sync_repository import AnalyticsSyncRepository


class FakeDatabase:
    def __init__(self, session) -> None:
        self._session = session

    async def session(self, tenant_id):
        yield self._session


class FakeSession:
    def __init__(self, run, report, cursor) -> None:
        self.run = run
        self.report = report
        self.cursor = cursor
        self.commits = 0

    async def get(self, model, value):
        if model is AnalyticsSyncRun and value == self.run.id:
            return self.run
        return None

    async def scalar(self, statement):
        entity = statement.column_descriptions[0].get("entity")
        return self.report if entity is AffiliateCreatorReport else self.cursor

    async def commit(self) -> None:
        self.commits += 1


def test_partial_creator_run_keeps_previous_complete_snapshot_and_cursor() -> None:
    tenant_id, shop_id = uuid4(), uuid4()
    run = AnalyticsSyncRun(
        id=uuid4(),
        tenant_id=tenant_id,
        shop_id=shop_id,
        resource_type="affiliate_creator",
        job_id="affiliate:test",
        status="running",
        attempt_count=1,
        window_start=datetime(2026, 8, 1, tzinfo=UTC),
        window_end=datetime(2026, 8, 2, tzinfo=UTC),
        fetched_count=570,
        persisted_count=570,
    )
    current_report = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        shop_id=shop_id,
        status="running",
        expected_total=None,
        pages_fetched=0,
        records_received=0,
        records_unique=0,
        duplicate_count=0,
        completeness_reason=None,
    )
    previous_report = SimpleNamespace(status="complete", records_unique=572)
    cursor = SimpleNamespace(committed_cursor="complete:page:12")
    session = FakeSession(run, current_report, cursor)
    repository = AnalyticsSyncRepository(FakeDatabase(session))

    result = asyncio.run(
        repository.partial_run(
            tenant_id,
            run.id,
            reason="total_count_mismatch",
            creator_report_id=current_report.id,
            report_partial=AffiliateCreatorReportPartial(
                expected_total=572,
                pages_fetched=12,
                records_received=570,
                records_unique=570,
                duplicate_count=0,
                completeness_reason="total_count_mismatch",
            ),
        )
    )

    assert result.status == current_report.status == "partial"
    assert previous_report.status == "complete"
    assert previous_report.records_unique == 572
    assert cursor.committed_cursor == "complete:page:12"
    assert session.commits == 1
