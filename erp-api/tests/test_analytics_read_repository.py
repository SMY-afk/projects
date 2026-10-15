import asyncio
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from erp_api.services.analytics_read_repository import AnalyticsReadRepository


class FakeResult:
    def __init__(self, rows=()):
        self.rows = rows

    def all(self):
        return self.rows

    def __iter__(self):
        return iter(self.rows)

    def scalars(self):
        return self


class FakeSession:
    def __init__(self, rows=()) -> None:
        self.statement = None
        self.rows = rows
        self.execute_count = 0

    async def execute(self, statement):
        if self.execute_count == 0:
            self.statement = statement
        rows = self.rows if self.execute_count == 0 else ()
        self.execute_count += 1
        return FakeResult(rows)

    async def scalar(self, statement):
        self.statement = statement


class FakeDatabase:
    def __init__(self, session: FakeSession) -> None:
        self._session = session

    async def session(self, tenant_id):
        yield self._session


def _compiled_sql(statement) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


def test_video_ranking_sorts_by_numeric_gmv_before_limit() -> None:
    session = FakeSession()
    repository = AnalyticsReadRepository(FakeDatabase(session))

    asyncio.run(
        repository.list_content(
            uuid4(),
            uuid4(),
            resource_type="video",
            limit=50,
            sort_by="gmv",
            sort_order="desc",
        )
    )

    sql = _compiled_sql(session.statement)
    order_by = sql.split("ORDER BY", maxsplit=1)[1]
    assert "tiktok_video_contents.fields ->> 'gmvAmount'" in order_by
    assert " AS NUMERIC" in order_by
    assert " DESC NULLS LAST" in order_by
    assert order_by.index("gmvAmount") < order_by.index("LIMIT 50")


def test_live_ranking_filters_account_type_before_sort_and_limit() -> None:
    session = FakeSession()
    repository = AnalyticsReadRepository(FakeDatabase(session))

    asyncio.run(
        repository.list_content(
            uuid4(),
            uuid4(),
            resource_type="live",
            limit=50,
            sort_by="gmv",
            sort_order="desc",
            account_type="AFFILIATE_ACCOUNTS",
        )
    )

    sql = _compiled_sql(session.statement)
    assert "tiktok_live_sessions.fields ->> 'accountType'" in sql
    assert "= 'AFFILIATE_ACCOUNTS'" in sql
    assert sql.index("accountType") < sql.index("ORDER BY") < sql.index("LIMIT 50")


def test_live_ranking_filters_start_time_before_sort_and_limit() -> None:
    session = FakeSession()
    repository = AnalyticsReadRepository(FakeDatabase(session))

    asyncio.run(
        repository.list_content(
            uuid4(),
            uuid4(),
            resource_type="live",
            limit=50,
            sort_by="gmv",
            sort_order="desc",
            window_start=datetime(2026, 8, 1, tzinfo=UTC),
            window_end=datetime(2026, 8, 8, tzinfo=UTC),
            account_type="AFFILIATE_ACCOUNTS",
        )
    )

    sql = _compiled_sql(session.statement)
    assert "tiktok_live_sessions.fields ->> 'startTime'" in sql
    assert ">= 1785542400" in sql
    assert "< 1786147200" in sql
    assert sql.index("startTime") < sql.index("ORDER BY") < sql.index("LIMIT 50")


def test_windowed_video_ranking_reads_only_the_latest_succeeded_batch() -> None:
    session = FakeSession()
    repository = AnalyticsReadRepository(FakeDatabase(session))
    tenant_id, shop_id = uuid4(), uuid4()

    rows = asyncio.run(
        repository.list_content(
            tenant_id,
            shop_id,
            resource_type="video",
            limit=50,
            sort_by="gmv",
            sort_order="desc",
            window_start=datetime(2026, 8, 13, tzinfo=UTC),
            window_end=datetime(2026, 8, 20, tzinfo=UTC),
            currency="USD",
            account_type="ALL",
        )
    )

    assert rows == []
    sql = _compiled_sql(session.statement)
    assert "tiktok_video_performance_snapshots" in sql
    assert "analytics_sync_runs.status = 'succeeded'" in sql
    assert "analytics_sync_runs.resource_type = 'video'" in sql
    assert "tiktok_video_contents.fields" in sql
    assert "tiktok_video_performance_snapshots.metrics" in sql
    assert "tiktok_video_performance_snapshots.currency = 'USD'" in sql
    assert "tiktok_video_performance_snapshots.account_type = 'ALL'" in sql
    assert "tiktok_video_performance_snapshots.window_start = '2026-08-13" in sql
    assert "tiktok_video_performance_snapshots.window_end = '2026-08-20" in sql
    assert sql.count("tiktok_video_performance_snapshots.window_start =") == 2
    assert sql.count("tiktok_video_performance_snapshots.window_end =") == 2
    assert sql.count("tiktok_video_performance_snapshots.currency =") == 2
    assert sql.count("tiktok_video_performance_snapshots.account_type =") == 2
    assert sql.count("tiktok_video_performance_snapshots.tenant_id =") >= 2
    assert sql.count("tiktok_video_performance_snapshots.shop_id =") >= 2
    assert (
        "tiktok_video_contents.tenant_id = tiktok_video_performance_snapshots.tenant_id"
        in sql
    )
    assert (
        "tiktok_video_contents.shop_id = tiktok_video_performance_snapshots.shop_id"
        in sql
    )
    order_by = sql.rsplit("ORDER BY", maxsplit=1)[1]
    assert "tiktok_video_performance_snapshots.metrics ->> 'gmvAmount'" in order_by
    assert order_by.index("gmvAmount") < order_by.index("LIMIT 50")


def test_video_window_state_is_exact_and_tenant_scoped() -> None:
    session = FakeSession()
    repository = AnalyticsReadRepository(FakeDatabase(session))
    tenant_id, shop_id = uuid4(), uuid4()

    state = asyncio.run(
        repository.get_video_window_state(
            tenant_id,
            shop_id,
            window_start=datetime(2026, 8, 19, tzinfo=UTC),
            window_end=datetime(2026, 8, 20, tzinfo=UTC),
            currency="USD",
            account_type="ALL",
        )
    )

    assert state is None
    sql = _compiled_sql(session.statement)
    assert f"analytics_sync_runs.tenant_id = '{tenant_id}'" in sql
    assert f"analytics_sync_runs.shop_id = '{shop_id}'" in sql
    assert "analytics_sync_runs.resource_type = 'video'" in sql
    assert "analytics_sync_runs.status = 'succeeded'" in sql
    assert "analytics_sync_runs.currency = 'USD'" in sql
    assert "analytics_sync_runs.account_type = 'ALL'" in sql
    assert "analytics_sync_runs.window_start = '2026-08-19" in sql
    assert "analytics_sync_runs.window_end = '2026-08-20" in sql


def test_windowed_video_ranking_never_falls_back_to_latest_content_metrics() -> None:
    observed_at = datetime(2026, 8, 19, tzinfo=UTC)
    session = FakeSession(
        [
            (
                "video-1",
                {
                    "title": "Video",
                    "views": 999,
                    "gmvAmount": "999.00",
                    "latestOnlyMetric": 123,
                },
                {"views": 308, "gmvAmount": "12.34"},
                None,
                None,
                observed_at,
                observed_at,
                None,
            )
        ]
    )
    repository = AnalyticsReadRepository(FakeDatabase(session))

    rows = asyncio.run(
        repository.list_content(
            uuid4(),
            uuid4(),
            resource_type="video",
            limit=50,
            sort_by="gmv",
            sort_order="desc",
            window_start=datetime(2026, 8, 13, tzinfo=UTC),
            window_end=datetime(2026, 8, 20, tzinfo=UTC),
            currency="USD",
            account_type="ALL",
        )
    )

    assert rows[0].fields == {
        "title": "Video",
        "views": 308,
        "gmvAmount": "12.34",
    }


def test_windowed_video_ranking_merges_retention_stages_by_exact_video_id() -> None:
    observed_at = datetime(2026, 8, 19, tzinfo=UTC)
    session = FakeSession(
        [
            (
                "video-1",
                {"title": "Video"},
                {"views": 308},
                None,
                None,
                observed_at,
                observed_at,
                {
                    "completion_rate": "0.001761",
                    "completion_second": 28,
                    "retention_stages": {
                        "2s": {"second": 2, "rate": "0.077947"},
                        "6s": {"second": 6, "rate": "0.032319"},
                        "25%": {"second": 8, "rate": "0.025"},
                        "50%": {"second": 15, "rate": "0.015"},
                        "75%": {"second": 22, "rate": "0.008"},
                        "100%": {"second": 28, "rate": "0.001761"},
                    },
                },
            )
        ]
    )
    repository = AnalyticsReadRepository(FakeDatabase(session))

    rows = asyncio.run(
        repository.list_content(
            uuid4(),
            uuid4(),
            resource_type="video",
            limit=50,
            sort_by="gmv",
            sort_order="desc",
            window_start=datetime(2026, 8, 13, tzinfo=UTC),
            window_end=datetime(2026, 8, 20, tzinfo=UTC),
            currency="USD",
            account_type="ALL",
        )
    )

    sql = _compiled_sql(session.statement)
    assert "seller_video_completion:" in sql
    assert "scraped_data.data_type = 'seller_video_completion'" in sql
    assert rows[0].fields == {
        "title": "Video",
        "views": 308,
        "completionRate": "0.001761",
        "completionSecond": 28,
        "retention2sRate": "0.077947",
        "retention6sRate": "0.032319",
        "retention25Rate": "0.025",
        "retention50Rate": "0.015",
        "retention75Rate": "0.008",
        "retention100Rate": "0.001761",
    }


def test_video_ranking_can_sort_by_gpm_and_publish_time() -> None:
    for sort_by, expected in (
        ("gpm", "tiktok_video_contents.fields ->> 'gpmAmount'"),
        ("publishedAt", "tiktok_video_contents.fields ->> 'videoPostTime'"),
    ):
        session = FakeSession()
        repository = AnalyticsReadRepository(FakeDatabase(session))

        asyncio.run(
            repository.list_content(
                uuid4(),
                uuid4(),
                resource_type="video",
                limit=50,
                sort_by=sort_by,
                sort_order="desc",
            )
        )

        order_by = _compiled_sql(session.statement).split("ORDER BY", maxsplit=1)[1]
        assert expected in order_by
        assert " DESC NULLS LAST" in order_by


def test_video_ranking_merges_completion_rate_by_exact_video_id() -> None:
    observed_at = datetime(2026, 8, 19, tzinfo=UTC)
    session = FakeSession(
        [
            (
                "video-1",
                {"title": "Video"},
                None,
                None,
                None,
                observed_at,
                {
                    "completion_rate": "0.001761",
                    "completion_second": 28,
                    "retention_stages": {
                        "2s": {"second": 2, "rate": "0.077947"},
                        "6s": {"second": 6, "rate": "0.032319"},
                        "25%": {"second": 8, "rate": "0.025"},
                        "50%": {"second": 15, "rate": "0.015"},
                        "75%": {"second": 22, "rate": "0.008"},
                        "100%": {"second": 28, "rate": "0.001761"},
                    },
                },
            )
        ]
    )
    repository = AnalyticsReadRepository(FakeDatabase(session))

    rows = asyncio.run(
        repository.list_content(
            uuid4(),
            uuid4(),
            resource_type="video",
            limit=50,
            sort_by="gmv",
            sort_order="desc",
        )
    )

    sql = _compiled_sql(session.statement)
    assert "seller_video_completion:" in sql
    assert "scraped_data.data_type = 'seller_video_completion'" in sql
    assert rows[0].fields == {
        "title": "Video",
        "completionRate": "0.001761",
        "completionSecond": 28,
        "retention2sRate": "0.077947",
        "retention6sRate": "0.032319",
        "retention25Rate": "0.025",
        "retention50Rate": "0.015",
        "retention75Rate": "0.008",
        "retention100Rate": "0.001761",
    }


def test_live_ranking_sorts_by_numeric_gmv_before_limit() -> None:
    session = FakeSession()
    repository = AnalyticsReadRepository(FakeDatabase(session))

    asyncio.run(
        repository.list_content(
            uuid4(),
            uuid4(),
            resource_type="live",
            limit=50,
            sort_by="gmv",
            sort_order="desc",
        )
    )

    order_by = _compiled_sql(session.statement).split("ORDER BY", maxsplit=1)[1]
    assert "tiktok_live_sessions.fields ->> 'gmvAmount'" in order_by
    assert " AS NUMERIC" in order_by
    assert " DESC NULLS LAST" in order_by
    assert order_by.index("gmvAmount") < order_by.index("LIMIT 50")


def test_live_ranking_can_sort_by_latest_start_time() -> None:
    session = FakeSession()
    repository = AnalyticsReadRepository(FakeDatabase(session))

    asyncio.run(
        repository.list_content(
            uuid4(),
            uuid4(),
            resource_type="live",
            limit=50,
            sort_by="startedAt",
            sort_order="desc",
        )
    )

    order_by = _compiled_sql(session.statement).split("ORDER BY", maxsplit=1)[1]
    assert "tiktok_live_sessions.fields ->> 'startTime'" in order_by
    assert " DESC NULLS LAST" in order_by
