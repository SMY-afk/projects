import asyncio
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from typing import get_args
from uuid import uuid4

import pytest

from erp_api.models.affiliate_creator import AffiliateCreatorReport
from erp_api.models.analytics_sync import (
    AnalyticsRawPayload,
    AnalyticsSyncCursor,
    AnalyticsSyncRun,
)
from erp_api.services.affiliate_creator_report_completion import (
    AffiliateCreatorReportCompletion,
)
from erp_api.services.analytics_resource_types import AnalyticsSyncResourceType
from erp_api.services.analytics_sync_repository import AnalyticsSyncRepository


def test_sync_resource_type_includes_affiliate_center_resources() -> None:
    assert set(get_args(AnalyticsSyncResourceType)) == {
        "video",
        "live",
        "affiliate_creator",
        "affiliate_video",
        "affiliate_creator_detail",
    }


class FakeDatabase:
    def __init__(self, session) -> None:
        self._session = session

    async def session(self, tenant_id):
        yield self._session


class FakeSession:
    def __init__(
        self, run, report=None, *, previous_report=None, recorded_raw=False
    ) -> None:
        self.run = run
        self.report = report
        self.previous_report = previous_report
        self.recorded_raw = recorded_raw
        self.added = []
        self.commits = 0
        self.cursor = None
        self.report_reads = 0

    async def get(self, model, value):
        if model is AnalyticsSyncRun and value == self.run.id:
            return self.run
        if (
            model is AffiliateCreatorReport
            and self.report is not None
            and value == self.report.id
        ):
            return self.report
        return None

    async def scalar(self, statement):
        entity = statement.column_descriptions[0].get("entity")
        if entity is AffiliateCreatorReport:
            self.report_reads += 1
            return self.report if self.report_reads == 1 else self.previous_report
        if entity is AnalyticsRawPayload:
            return uuid4() if self.recorded_raw else None
        return self.cursor

    def add(self, value) -> None:
        self.added.append(value)
        if isinstance(value, AnalyticsSyncCursor):
            self.cursor = value

    async def execute(self, statement):
        return SimpleNamespace(rowcount=2)

    async def commit(self) -> None:
        self.commits += 1


def _run(tenant_id, shop_id) -> AnalyticsSyncRun:
    return AnalyticsSyncRun(
        id=uuid4(),
        tenant_id=tenant_id,
        shop_id=shop_id,
        resource_type="video",
        job_id="analytics-sync:shop:video",
        status="running",
        attempt_count=1,
        window_start=datetime(2026, 8, 1, tzinfo=UTC),
        window_end=datetime(2026, 8, 2, tzinfo=UTC),
        fetched_count=0,
        persisted_count=0,
    )


def test_cursor_is_only_created_and_committed_after_full_sync_success() -> None:
    tenant_id, shop_id = uuid4(), uuid4()
    run = _run(tenant_id, shop_id)
    session = FakeSession(run)
    repository = AnalyticsSyncRepository(FakeDatabase(session), raw_payload_ttl_days=7)
    source_updated_at = datetime(2026, 8, 1, 2, tzinfo=UTC)

    asyncio.run(
        repository.record_page(
            tenant_id,
            run.id,
            next_cursor="page-2",
            fetched_count=10,
            persisted_count=8,
            platform_request_id="request-1",
            source_updated_at=source_updated_at,
            raw_payload_kind="video_page",
            page_number=1,
            raw_payload={
                "data": {
                    "items": [
                        {
                            "id": "video-1",
                            "headers": {"Cookie": "secret"},
                            "profile": {
                                "email": "private@example.test",
                                "metric": 7,
                            },
                        }
                    ]
                },
                "access_token": "secret",
            },
            latest_available_date=date(2026, 8, 17),
        )
    )

    assert session.cursor is None
    assert run.recovery_cursor == "page-2"
    assert run.fetched_count == 10
    assert run.latest_available_date == date(2026, 8, 17)
    assert isinstance(session.added[0], AnalyticsRawPayload)
    assert session.added[0].payload == {
        "data": {"items": [{"id": "video-1", "profile": {"metric": 7}}]},
        "_erp_capture": {"pageNumber": 1},
    }
    assert session.added[0].expires_at > datetime.now(UTC) + timedelta(days=6)

    result = asyncio.run(repository.complete_run(tenant_id, run.id))

    assert result.status == "succeeded"
    assert session.cursor.committed_cursor == "page-2"
    assert session.cursor.fresh_at == source_updated_at
    assert session.commits == 2


def test_affiliate_creator_completion_marks_report_and_cursor_atomically() -> None:
    tenant_id, shop_id = uuid4(), uuid4()
    run = _run(tenant_id, shop_id)
    run.resource_type = "affiliate_creator"
    run.recovery_cursor = "page:2"
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
    session = FakeSession(run, report)
    repository = AnalyticsSyncRepository(FakeDatabase(session))

    result = asyncio.run(
        repository.complete_run(
            tenant_id,
            run.id,
            creator_report_id=report.id,
            report_completion=AffiliateCreatorReportCompletion(
                expected_total=2,
                pages_fetched=2,
                records_received=2,
                records_unique=2,
                duplicate_count=0,
                completeness_reason="complete",
            ),
        )
    )

    assert result.status == "succeeded"
    assert report.status == "complete"
    assert report.pages_fetched == 2
    assert report.records_unique == 2
    assert session.cursor.committed_cursor == "page:2"
    assert session.commits == 1


def test_affiliate_raw_payload_repository_defaults_to_seven_day_ttl() -> None:
    tenant_id, shop_id = uuid4(), uuid4()
    run = _run(tenant_id, shop_id)
    run.resource_type = "affiliate_video"
    session = FakeSession(run)
    repository = AnalyticsSyncRepository.for_affiliate_center(FakeDatabase(session))

    asyncio.run(
        repository.record_page(
            tenant_id,
            run.id,
            next_cursor="page:2",
            fetched_count=1,
            persisted_count=1,
            platform_request_id="request-1",
            source_updated_at=None,
            raw_payload_kind="affiliate_video_page",
            raw_payload={"data": {"email": "private", "metric": 1}},
        )
    )

    raw = session.added[0]
    assert isinstance(raw, AnalyticsRawPayload)
    assert raw.payload == {"data": {"metric": 1}}
    assert datetime.now(UTC) + timedelta(days=6) < raw.expires_at
    assert raw.expires_at < datetime.now(UTC) + timedelta(days=8)


def test_page_audit_rejects_missing_platform_request_id() -> None:
    tenant_id, shop_id = uuid4(), uuid4()
    run = _run(tenant_id, shop_id)
    repository = AnalyticsSyncRepository(FakeDatabase(FakeSession(run)))

    with pytest.raises(ValueError, match="platform_request_id"):
        asyncio.run(
            repository.record_page(
                tenant_id,
                run.id,
                next_cursor=None,
                fetched_count=1,
                persisted_count=1,
                platform_request_id=None,
                source_updated_at=None,
                raw_payload_kind="live_page",
                raw_payload={"data": {"live_stream_sessions": []}},
            )
        )


def test_failed_run_keeps_cursor_uncommitted_and_records_safe_summary() -> None:
    tenant_id, shop_id = uuid4(), uuid4()
    run = _run(tenant_id, shop_id)
    session = FakeSession(run)
    repository = AnalyticsSyncRepository(FakeDatabase(session))

    result = asyncio.run(
        repository.fail_run(
            tenant_id,
            run.id,
            category="rate_limited",
        )
    )

    assert result.status == "failed"
    assert session.cursor is None
    assert result.error_summary == "Analytics platform rate limit was reached."


def test_retry_wait_run_reenters_running_without_reusing_a_page_cursor() -> None:
    tenant_id, shop_id = uuid4(), uuid4()
    run = _run(tenant_id, shop_id)
    run.status = "retry_wait"
    run.start_cursor = "2026-08-01T00:00:00+00:00"
    run.recovery_cursor = "page-3"
    run.fetched_count = 20
    run.persisted_count = 18
    session = FakeSession(run)
    repository = AnalyticsSyncRepository(FakeDatabase(session))

    asyncio.run(repository.start_run(tenant_id, run.id))

    assert run.status == "running"
    assert run.attempt_count == 2
    assert run.recovery_cursor == run.start_cursor
    assert run.fetched_count == 0
    assert run.persisted_count == 0


def test_purge_raw_payloads_is_tenant_scoped() -> None:
    repository = AnalyticsSyncRepository(
        FakeDatabase(FakeSession(_run(uuid4(), uuid4())))
    )

    removed = asyncio.run(repository.purge_expired_raw_payloads(uuid4()))

    assert removed == 2
