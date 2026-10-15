import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from erp_api.services.analytics_repository import (
    AnalyticsRepository,
    AnalyticsSnapshotInput,
)
from erp_api.services.tiktok_data_schemas import TikTokAnalyticsItem


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


def _item(
    external_id: str, *, updated_at: datetime | None = None
) -> TikTokAnalyticsItem:
    return TikTokAnalyticsItem(
        fields={"externalId": external_id, "views": 3},
        source_status="ENDED",
        status="ended",
        source_updated_at=updated_at,
    )


def _sql(statement) -> str:
    return str(statement.compile(dialect=postgresql.dialect()))


def test_snapshot_upsert_deduplicates_windows_and_uses_a_unique_constraint() -> None:
    tenant_id, shop_id = uuid4(), uuid4()
    session = FakeSession()
    repository = AnalyticsRepository(FakeDatabase(session))
    start = datetime(2026, 8, 1, tzinfo=UTC)
    snapshots = [
        AnalyticsSnapshotInput(
            "shop",
            "day",
            start,
            start + timedelta(days=1),
            "usd",
            {"views": 1},
            None,
            "r1",
        ),
        AnalyticsSnapshotInput(
            "shop",
            "day",
            start,
            start + timedelta(days=1),
            "USD",
            {"views": 2},
            None,
            "r2",
        ),
    ]

    applied = asyncio.run(repository.upsert_snapshots(tenant_id, shop_id, snapshots))

    assert applied == 1
    assert session.commits == 1
    sql = _sql(session.statements[0])
    assert (
        "ON CONFLICT ON CONSTRAINT uq_analytics_snapshots_shop_metric_window_currency"
        in sql
    )
    assert "analytics_snapshots.metrics || excluded.metrics" in sql


def test_content_upserts_are_batched_and_keyed_by_platform_external_id() -> None:
    tenant_id, shop_id = uuid4(), uuid4()
    session = FakeSession()
    repository = AnalyticsRepository(FakeDatabase(session))
    updated_at = datetime(2026, 8, 1, 1, tzinfo=UTC)

    video_count = asyncio.run(
        repository.upsert_video_contents(
            tenant_id,
            shop_id,
            [
                _item("video-1"),
                _item("video-1", updated_at=updated_at),
                _item("video-2"),
            ],
            external_id_field="externalId",
            platform_request_id="request-1",
        )
    )
    live_count = asyncio.run(
        repository.upsert_live_sessions(
            tenant_id,
            shop_id,
            [_item("live-1", updated_at=updated_at)],
            external_id_field="externalId",
            platform_request_id="request-2",
        )
    )

    assert video_count == 2
    assert live_count == 1
    assert session.commits == 2
    assert (
        "ON CONFLICT ON CONSTRAINT uq_tiktok_video_contents_shop_platform_video"
        in _sql(session.statements[0])
    )
    assert (
        "ON CONFLICT ON CONSTRAINT uq_tiktok_live_sessions_shop_platform_live"
        in _sql(session.statements[1])
    )
    assert "source_updated_at" in _sql(session.statements[0])


def test_official_video_upsert_preserves_existing_rich_browser_metadata() -> None:
    session = FakeSession()
    repository = AnalyticsRepository(FakeDatabase(session))

    asyncio.run(
        repository.upsert_video_contents(
            uuid4(),
            uuid4(),
            [_item("video-1")],
            external_id_field="externalId",
            platform_request_id="request-1",
            preserve_existing_details=True,
        )
    )

    sql = _sql(session.statements[0])
    params = list(
        session.statements[0].compile(dialect=postgresql.dialect()).params.values()
    )
    assert "CASE WHEN" in sql
    assert "jsonb_set" in sql
    assert all(
        field in params
        for field in (
            "coverImageUrl",
            "creatorAvatarUrl",
            "promotedProducts",
            "creatorUsername",
            "creatorNickname",
        )
    )


def test_content_upsert_requires_a_non_empty_string_external_id() -> None:
    repository = AnalyticsRepository(FakeDatabase(FakeSession()))

    with pytest.raises(ValueError, match="externalId"):
        asyncio.run(
            repository.upsert_video_contents(
                uuid4(),
                uuid4(),
                [_item("")],
                external_id_field="externalId",
                platform_request_id=None,
            )
        )


def test_content_upsert_rejects_items_without_platform_request_id() -> None:
    repository = AnalyticsRepository(FakeDatabase(FakeSession()))

    with pytest.raises(ValueError, match="platform_request_id"):
        asyncio.run(
            repository.upsert_live_sessions(
                uuid4(),
                uuid4(),
                [_item("live-1")],
                external_id_field="externalId",
                platform_request_id=None,
            )
        )


def test_snapshot_requires_a_complete_granularity_window() -> None:
    repository = AnalyticsRepository(FakeDatabase(FakeSession()))
    start = datetime(2026, 8, 1, tzinfo=UTC)

    with pytest.raises(ValueError, match="exactly one day"):
        asyncio.run(
            repository.upsert_snapshots(
                uuid4(),
                uuid4(),
                [
                    AnalyticsSnapshotInput(
                        "shop",
                        "day",
                        start,
                        start + timedelta(hours=1),
                        "USD",
                        {},
                        None,
                        None,
                    )
                ],
            )
        )
