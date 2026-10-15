import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from erp_api.services.affiliate_sample_priority import (
    sample_round_allows_affiliate,
    sample_round_releases_affiliate,
)


class _Session:
    def __init__(self, sample_finished_at: datetime) -> None:
        self.sample_finished_at = sample_finished_at
        self.statements = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def scalar(self, statement):
        self.statements.append(statement)
        return SimpleNamespace(status="succeeded", finished_at=self.sample_finished_at)


class _Database:
    def __init__(self, sample_finished_at: datetime) -> None:
        self.session = _Session(sample_finished_at)

    def system_session_factory(self):
        return self.session


def test_sample_round_releases_first_affiliate_task_in_daily_window() -> None:
    window_start = datetime(2026, 9, 14, 15, 30, tzinfo=UTC)

    assert sample_round_allows_affiliate(
        sample_status="succeeded",
        sample_finished_at=window_start + timedelta(minutes=1),
        window_start=window_start,
    )


def test_completed_sample_allows_more_than_one_affiliate_window() -> None:
    window_start = datetime(2026, 9, 14, 15, 30, tzinfo=UTC)
    assert sample_round_allows_affiliate(
        sample_status="succeeded",
        sample_finished_at=window_start + timedelta(minutes=3),
        window_start=window_start,
    )


def test_active_or_failed_sample_blocks_affiliate_window() -> None:
    window_start = datetime(2026, 9, 14, 15, 30, tzinfo=UTC)
    assert not sample_round_allows_affiliate(
        sample_status="running",
        sample_finished_at=None,
        window_start=window_start,
    )
    assert not sample_round_allows_affiliate(
        sample_status="partial",
        sample_finished_at=window_start + timedelta(minutes=5),
        window_start=window_start,
    )


def test_old_sample_round_does_not_release_new_daily_window() -> None:
    window_start = datetime(2026, 9, 14, 15, 30, tzinfo=UTC)

    assert not sample_round_allows_affiliate(
        sample_status="succeeded",
        sample_finished_at=window_start - timedelta(seconds=1),
        window_start=window_start,
    )


def test_real_sample_capture_round_releases_daytime_scheduled_backlog() -> None:
    database = _Database(datetime(2026, 9, 17, 5, 20, tzinfo=UTC))

    released = asyncio.run(
        sample_round_releases_affiliate(
            database,
            uuid4(),
            uuid4(),
            now=datetime(2026, 9, 17, 5, 30, tzinfo=UTC),
        )
    )

    sample_query = database.session.statements[0].compile(
        dialect=postgresql.dialect()
    )
    assert released
    assert "source_to_postgres" in sample_query.params.values()
    assert "postgres_to_feishu" not in sample_query.params.values()
