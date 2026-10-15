import asyncio
from datetime import date
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from erp_api.models.affiliate_creator import AffiliateCreatorMetric
from erp_api.services.affiliate_center_contract import (
    AffiliateCenterQuery,
    AffiliateCenterResource,
)
from erp_api.services.affiliate_center_read_queries import (
    complete_video_run,
    latest_failure_run,
)
from erp_api.services.affiliate_center_read_repository import (
    AffiliateCenterReadRepository,
)
from erp_api.services.affiliate_center_summary import (
    creator_summary_from_row,
    video_summary_statement,
)
from erp_api.services.affiliate_creator_avatar_query import (
    video_avatars_for_usernames,
)
from erp_api.services.affiliate_creator_page_query import creator_summary_for_report
from erp_api.services.affiliate_creator_read_models import creator_metric_dict


class FakeSession:
    def __init__(self) -> None:
        self.statements = []

    async def scalar(self, statement):
        self.statements.append(statement)

    async def execute(self, statement):
        self.statements.append(statement)
        return SimpleNamespace(scalars=list)


class FakeDatabase:
    def __init__(self) -> None:
        self.session_instance = FakeSession()

    async def session(self, tenant_id):
        yield self.session_instance


class FakeLatestDateSession(FakeSession):
    def __init__(self) -> None:
        super().__init__()
        self.values = iter(
            [
                "America/Los_Angeles",
                date(2026, 9, 2),
                date(2026, 9, 1),
                date(2026, 8, 31),
            ]
        )

    async def scalar(self, statement):
        self.statements.append(statement)
        return next(self.values)


class FakeLatestDateDatabase(FakeDatabase):
    def __init__(self) -> None:
        self.session_instance = FakeLatestDateSession()


def _query(resource):
    return AffiliateCenterQuery(
        resource=resource,
        shop_id=uuid4(),
        window_start=date(2026, 8, 1),
        window_end=date(2026, 8, 7),
        shop_timezone="America/Los_Angeles",
        currency="USD",
        filters={},
    )


def _sql(statement) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


def test_creator_read_selects_only_an_exact_complete_snapshot() -> None:
    database = FakeDatabase()
    repository = AffiliateCenterReadRepository(database)  # type: ignore[arg-type]
    tenant_id = uuid4()
    query = _query(AffiliateCenterResource.CREATORS)

    result = asyncio.run(
        repository.list_creators(
            tenant_id,
            query,
            page=1,
            page_size=50,
            sort="affiliateGmvMinor",
            order="desc",
        )
    )

    sql = _sql(database.session_instance.statements[0])
    assert result["items"] == []
    assert result["summary"] == {
        "creatorCount": 0,
        "affiliateGmvMinor": 0,
        "estimatedCommissionMinor": 0,
        "itemsSold": 0,
        "affiliateOrderCount": 0,
        "productImpressions": 0,
    }
    assert f"affiliate_creator_reports.tenant_id = '{tenant_id}'" in sql
    assert f"affiliate_creator_reports.shop_id = '{query.shop_id}'" in sql
    assert "affiliate_creator_reports.period_start = '2026-08-01'" in sql
    assert "affiliate_creator_reports.period_end = '2026-08-07'" in sql
    assert "affiliate_creator_reports.shop_timezone = 'America/Los_Angeles'" in sql
    assert "affiliate_creator_reports.currency = 'USD'" in sql
    assert "affiliate_creator_reports.status = 'complete'" in sql
    assert "partial" not in sql


def test_latest_available_dates_are_restored_from_complete_snapshots() -> None:
    database = FakeLatestDateDatabase()
    repository = AffiliateCenterReadRepository(database)  # type: ignore[arg-type]
    tenant_id = uuid4()
    shop_id = uuid4()

    result = asyncio.run(repository.latest_available_dates(tenant_id, shop_id))

    assert result == {
        "creators": date(2026, 9, 2),
        "videos": date(2026, 9, 1),
        "liveAccounts": date(2026, 8, 31),
    }
    creator_sql = _sql(database.session_instance.statements[1])
    video_sql = _sql(database.session_instance.statements[2])
    assert "affiliate_creator_reports.status = 'complete'" in creator_sql
    assert "analytics_sync_runs.resource_type = 'affiliate_video'" in video_sql
    assert "analytics_sync_runs.status = 'succeeded'" in video_sql
    live_sql = _sql(database.session_instance.statements[3])
    assert "analytics_sync_runs.resource_type = 'live'" in live_sql
    assert "analytics_sync_runs.account_type = 'AFFILIATE_ACCOUNTS'" in live_sql


def test_creator_metric_response_includes_the_master_avatar_url() -> None:
    metric = SimpleNamespace(
        **{column.name: None for column in AffiliateCreatorMetric.__table__.columns}
    )
    creator = SimpleNamespace(
        id=uuid4(),
        username="@creator",
        creator_open_id="creator-open-1",
        avatar_url="https://example.test/creator.jpg",
    )

    result = creator_metric_dict(creator, metric)

    assert result["avatarUrl"] == "https://example.test/creator.jpg"


def test_creator_summary_maps_null_totals_to_zero() -> None:
    result = creator_summary_from_row(
        SimpleNamespace(
            creator_count=2,
            affiliateGmvMinor=600,
            estimatedCommissionMinor=60,
            itemsSold=7,
            affiliateOrderCount=4,
            productImpressions=None,
        )
    )

    assert result == {
        "creatorCount": 2,
        "affiliateGmvMinor": 600,
        "estimatedCommissionMinor": 60,
        "itemsSold": 7,
        "affiliateOrderCount": 4,
        "productImpressions": 0,
    }


def test_official_xlsx_summary_preserves_unidentified_source_rows() -> None:
    row = SimpleNamespace(
        creator_count=2060,
        affiliateGmvMinor=686394,
        estimatedCommissionMinor=76371,
        itemsSold=89,
        affiliateOrderCount=87,
        productImpressions=0,
    )
    report = SimpleNamespace(
        source_metadata={
            "provider": "tiktok_compass_creator_xlsx_seller_center",
            "sourceRowCount": 2061,
            "unidentifiedRowCount": 1,
        }
    )

    result = creator_summary_for_report(row, report)

    assert result["creatorCount"] == 2061


def test_creator_metric_response_uses_video_avatar_when_master_avatar_is_missing() -> (
    None
):
    metric = SimpleNamespace(
        **{column.name: None for column in AffiliateCreatorMetric.__table__.columns}
    )
    creator = SimpleNamespace(
        id=uuid4(),
        username="@creator",
        creator_open_id="creator-open-1",
        avatar_url=None,
    )

    result = creator_metric_dict(
        creator,
        metric,
        fallback_avatar_url="https://example.test/video-creator.jpg",
    )

    assert result["avatarUrl"] == "https://example.test/video-creator.jpg"


def test_video_avatar_fallback_batches_the_current_page_without_correlation() -> None:
    tenant_id = uuid4()
    shop_id = uuid4()
    sql = _sql(
        video_avatars_for_usernames(
            tenant_id,
            shop_id,
            {"creator-one", "creator-two"},
        )
    )

    assert f"tiktok_video_contents.tenant_id = '{tenant_id}'" in sql
    assert f"tiktok_video_contents.shop_id = '{shop_id}'" in sql
    assert "creatorUsername" in sql
    assert "creatorAvatarUrl" in sql
    assert "creator-one" in sql
    assert "creator-two" in sql
    assert "affiliate_creators" not in sql


def test_video_read_uses_previous_browser_snapshot_only() -> None:
    tenant_id = uuid4()
    query = _query(AffiliateCenterResource.VIDEOS)
    window_start, window_end = query.utc_window()

    sql = _sql(complete_video_run(tenant_id, query, window_start, window_end))

    assert f"analytics_sync_runs.tenant_id = '{tenant_id}'" in sql
    assert f"analytics_sync_runs.shop_id = '{query.shop_id}'" in sql
    assert "analytics_sync_runs.resource_type = 'affiliate_video'" in sql
    assert "analytics_sync_runs.resource_type = 'video'" not in sql
    assert "analytics_sync_runs.status = 'succeeded'" in sql
    assert "analytics_sync_runs.currency = 'USD'" in sql
    assert "analytics_sync_runs.account_type = 'AFFILIATE_ACCOUNTS'" in sql
    assert "analytics_sync_runs.window_start = '2026-08-01" in sql
    assert "analytics_sync_runs.window_end = '2026-08-08" in sql
    assert "partial" not in sql


def test_video_summary_is_scoped_to_all_rows_matching_the_creator_filter() -> None:
    tenant_id = uuid4()
    shop_id = uuid4()
    run_id = uuid4()

    sql = _sql(
        video_summary_statement(
            tenant_id,
            shop_id,
            run_id,
            "creator-open-1",
        )
    )

    assert "count(*) AS video_count" in sql
    assert "sum(" in sql
    assert f"tiktok_video_performance_snapshots.tenant_id = '{tenant_id}'" in sql
    assert f"tiktok_video_performance_snapshots.shop_id = '{shop_id}'" in sql
    assert f"tiktok_video_performance_snapshots.sync_run_id = '{run_id}'" in sql
    assert "creatorOpenId" in sql
    assert "creator-open-1" in sql


def test_sync_failure_query_keeps_real_terminal_reason_available() -> None:
    tenant_id = uuid4()
    shop_id = uuid4()

    sql = _sql(latest_failure_run(tenant_id, shop_id, "affiliate_creator"))

    assert f"analytics_sync_runs.tenant_id = '{tenant_id}'" in sql
    assert f"analytics_sync_runs.shop_id = '{shop_id}'" in sql
    assert "analytics_sync_runs.resource_type = 'affiliate_creator'" in sql
    assert "analytics_sync_runs.status IN ('partial', 'failed', 'dead_letter')" in sql
