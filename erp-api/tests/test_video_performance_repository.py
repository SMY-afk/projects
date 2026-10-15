import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from erp_api.services.tiktok_data_schemas import TikTokAnalyticsItem
from erp_api.services.video_performance_repository import (
    VideoPerformanceRepository,
)


class FakeDatabase:
    def __init__(self, session) -> None:
        self._session = session

    async def session(self, tenant_id):
        yield self._session


class FakeSession:
    def __init__(self) -> None:
        self.statements = []
        self.commits = 0

    async def execute(self, statement) -> None:
        self.statements.append(statement)

    async def commit(self) -> None:
        self.commits += 1


def test_video_performance_page_is_batch_scoped_and_separates_metrics() -> None:
    session = FakeSession()
    repository = VideoPerformanceRepository(FakeDatabase(session))
    start = datetime(2026, 8, 13, 7, tzinfo=UTC)
    item = TikTokAnalyticsItem(
        fields={
            "videoId": "video-1",
            "title": "Video title",
            "creatorNickname": "Creator",
            "views": 308,
            "gmvAmount": "12.34",
            "gmvCurrency": "USD",
        },
        source_status="PUBLISHED",
        status="published",
        source_updated_at=datetime(2026, 8, 19, 7, 30, tzinfo=UTC),
    )

    applied = asyncio.run(
        repository.upsert_page(
            uuid4(),
            uuid4(),
            uuid4(),
            [item, item],
            window_start=start,
            window_end=start + timedelta(days=7),
            currency="usd",
            account_type="ALL",
            external_id_field="videoId",
            platform_request_id="request-1",
        )
    )

    assert applied == 1
    assert session.commits == 1
    statement = session.statements[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    params = statement.compile(dialect=postgresql.dialect()).params
    assert "ON CONFLICT ON CONSTRAINT uq_tiktok_video_performance_run_video" in sql
    assert "Video title" not in params.values()
    assert {
        "views": 308,
        "gmvAmount": "12.34",
        "gmvCurrency": "USD",
    } in params.values()
