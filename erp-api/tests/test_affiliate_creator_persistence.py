import asyncio
from datetime import UTC, date, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from erp_api.models.affiliate_creator import AffiliateCreatorReport
from erp_api.models.analytics_sync import AnalyticsSyncRun
from erp_api.services.affiliate_center_contract import (
    AffiliateCenterQuery,
    AffiliateCenterResource,
)
from erp_api.services.affiliate_center_metric_dtos import AffiliateCreatorMetricDTO
from erp_api.services.affiliate_center_source import (
    AffiliateCenterPageDTO,
    AffiliatePaginationDTO,
)
from erp_api.services.affiliate_creator_persistence import (
    AffiliateCreatorPersistence,
    _batches,
)
from erp_api.services.affiliate_creator_persistence_rows import creator_row


class FakeDatabase:
    def __init__(self, session) -> None:
        self.session_value = session

    async def session(self, _tenant_id):
        yield self.session_value


class FakeSession:
    def __init__(self, revision=0, *, running_report=None, running_run=None) -> None:
        self.revision = revision
        self.running_report = running_report
        self.running_run = running_run
        self.added = []
        self.executed = []
        self.commits = 0
        self.creator_id = uuid4()

    async def scalar(self, statement):
        self.executed.append(statement)
        if "max(" in str(statement).lower():
            return self.revision
        entity = statement.column_descriptions[0].get("entity")
        if entity is AffiliateCreatorReport:
            return self.running_report
        if entity is AnalyticsSyncRun:
            return self.running_run
        return None

    def add_all(self, values) -> None:
        self.added.extend(values)

    async def flush(self) -> None:
        return None

    async def execute(self, statement):
        self.executed.append(statement)
        if len(self.executed) == 1:
            return [SimpleNamespace(id=self.creator_id, username_normalized="creator")]
        return None

    async def commit(self) -> None:
        self.commits += 1


def _query() -> AffiliateCenterQuery:
    return AffiliateCenterQuery(
        resource=AffiliateCenterResource.CREATORS,
        shop_id=uuid4(),
        window_start=date(2026, 8, 1),
        window_end=date(2026, 8, 7),
        shop_timezone="America/Los_Angeles",
        currency="USD",
        filters={"collaboration_type": "target"},
    )


def _page(query: AffiliateCenterQuery) -> AffiliateCenterPageDTO:
    record = AffiliateCreatorMetricDTO(
        username="@Creator",
        username_normalized="creator",
        window_start_utc=query.utc_window()[0],
        window_end_utc=query.utc_window()[1],
        shop_timezone=query.shop_timezone,
        currency=query.currency,
        source_identifiers={"tiktok_page_creator_id": "private-1"},
        avatar_url="https://example.test/avatar.jpg",
        affiliate_gmv_minor=1234,
        estimated_commission_minor=123,
        affiliate_order_count=2,
        click_through_rate="0.05",
        extensions={"unconfirmed": "kept"},
    )
    return AffiliateCenterPageDTO(
        source_kind="page_capture",
        query=query,
        records=(record, record),
        pagination=AffiliatePaginationDTO(
            mode="page_page_size",
            page_number=1,
            has_more=False,
            total_count=1,
        ),
        request_id="request-1",
        source_updated_at=datetime(2026, 8, 8, tzinfo=UTC),
        raw_payload={"data": {}},
    )


def test_begin_capture_creates_running_report_revision_and_sync_run() -> None:
    session = FakeSession(revision=2)
    persistence = AffiliateCreatorPersistence(FakeDatabase(session))
    tenant_id, query = uuid4(), _query()

    result = asyncio.run(
        persistence.begin_capture(
            tenant_id,
            query,
            platform_shop_id="platform-shop-1",
            job_id="affiliate-page:test",
        )
    )

    run, report = session.added
    assert result == (run.id, report.id)
    assert run.tenant_id == report.tenant_id == tenant_id
    assert run.shop_id == report.shop_id == query.shop_id
    assert run.resource_type == "affiliate_creator"
    assert run.status == "running"
    assert run.attempt_count == 1
    assert report.revision_no == 3
    assert report.status == "running"
    assert report.source_kind == "page_capture"
    assert report.query_fingerprint == query.fingerprint
    assert report.filters == dict(query.filters)
    assert report.source_metadata == {
        "platformShopId": "platform-shop-1",
        "syncRunId": str(run.id),
    }
    assert session.commits == 1


def test_begin_capture_marks_browser_export_source() -> None:
    session = FakeSession()
    persistence = AffiliateCreatorPersistence(FakeDatabase(session))

    asyncio.run(
        persistence.begin_capture(
            uuid4(),
            _query(),
            platform_shop_id="platform-shop-1",
            job_id="affiliate-page:test",
            source_kind="browser_export",
        )
    )

    _, report = session.added
    assert report.source_kind == "browser_export"
    assert report.source_fingerprint.startswith("browser-export:")


def test_begin_capture_reuses_running_revision_after_daemon_reconnect() -> None:
    tenant_id, query = uuid4(), _query()
    run = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        shop_id=query.shop_id,
        resource_type="affiliate_creator",
        status="running",
    )
    report = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        shop_id=query.shop_id,
        source_metadata={
            "platformShopId": "platform-shop-1",
            "syncRunId": str(run.id),
        },
        source_fingerprint=f"page-capture:{run.id}",
    )
    session = FakeSession(running_report=report, running_run=run)
    persistence = AffiliateCreatorPersistence(FakeDatabase(session))

    result = asyncio.run(
        persistence.begin_capture(
            tenant_id,
            query,
            platform_shop_id="platform-shop-1",
            job_id="affiliate-page:reconnect",
        )
    )

    assert result == (run.id, report.id)
    assert session.added == []
    assert session.commits == 0


def test_begin_capture_claims_queued_creator_run_before_report_write() -> None:
    tenant_id, query = uuid4(), _query()
    window_start, window_end = query.utc_window()
    run = AnalyticsSyncRun(
        id=uuid4(),
        tenant_id=tenant_id,
        shop_id=query.shop_id,
        resource_type="affiliate_creator",
        job_id="affiliate-daily-backfill:test",
        status="queued",
        attempt_count=0,
        window_start=window_start,
        window_end=window_end,
        currency=query.currency,
        account_type="AFFILIATE_ACCOUNTS",
    )
    session = FakeSession(running_run=run)
    persistence = AffiliateCreatorPersistence(FakeDatabase(session))

    result = asyncio.run(
        persistence.begin_capture(
            tenant_id,
            query,
            platform_shop_id="platform-shop-1",
            job_id=run.job_id,
        )
    )

    report = session.added[0]
    assert result == (run.id, report.id)
    assert run.status == "running"
    assert run.attempt_count == 1
    assert report.status == "running"
    assert report.source_metadata["syncRunId"] == str(run.id)


def test_page_upsert_is_idempotent_inside_tenant_shop_report_scope() -> None:
    session = FakeSession()
    persistence = AffiliateCreatorPersistence(FakeDatabase(session))
    tenant_id, report_id, query = uuid4(), uuid4(), _query()

    persisted = asyncio.run(
        persistence.persist_page(tenant_id, report_id, _page(query))
    )

    assert persisted == 1
    assert len(session.executed) == 2
    creator_sql = str(session.executed[0])
    metric_sql = str(session.executed[1])
    assert "ON CONFLICT" in creator_sql
    assert "ON CONFLICT" in metric_sql
    assert "tenant_id" in creator_sql and "shop_id" in creator_sql
    assert "report_id" in metric_sql and "creator_id" in metric_sql
    assert session.commits == 1


def test_identity_refresh_replaces_an_expired_avatar_url() -> None:
    session = FakeSession()
    persistence = AffiliateCreatorPersistence(FakeDatabase(session))
    tenant_id, query = uuid4(), _query()
    record = _page(query).records[0]

    refreshed = asyncio.run(
        persistence.refresh_identities(tenant_id, query.shop_id, [record])
    )

    assert refreshed == 1
    statement = session.executed[0]
    assert "ON CONFLICT" in str(statement)
    assert statement.excluded.avatar_url is not None
    assert session.commits == 1


def test_large_creator_pages_are_split_below_asyncpg_parameter_limit() -> None:
    rows = [{"value": index} for index in range(1001)]

    batches = _batches(rows)

    assert [len(batch) for batch in batches] == [500, 500, 1]
    assert max(map(len, batches)) * 29 < 32767


def test_creator_persistence_rejects_video_pages() -> None:
    persistence = AffiliateCreatorPersistence(FakeDatabase(FakeSession()))
    page = SimpleNamespace(resource=AffiliateCenterResource.VIDEOS)

    with pytest.raises(ValueError, match="creator resource"):
        asyncio.run(persistence.persist_page(uuid4(), uuid4(), page))


def test_creator_identity_fields_are_stored_separately() -> None:
    tenant_id, shop_id = uuid4(), uuid4()
    record = AffiliateCreatorMetricDTO(
        username="@Creator",
        username_normalized="@creator",
        creator_open_id="open-1",
        avatar_url="https://example.test/avatar.jpg",
        source_identifiers={
            "tiktok_page_creator_id": "private-1",
            "creator_open_id": "must-not-shadow",
            "avatar_url": "must-not-shadow",
        },
        window_start_utc=datetime(2026, 8, 1, tzinfo=UTC),
        window_end_utc=datetime(2026, 8, 8, tzinfo=UTC),
        shop_timezone="America/Los_Angeles",
        currency="USD",
    )

    row = creator_row(tenant_id, shop_id, record)

    assert row["creator_open_id"] == "open-1"
    assert row["avatar_url"] == "https://example.test/avatar.jpg"
    assert row["source_identifiers"] == {"tiktok_page_creator_id": "private-1"}
