from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from erp_api.services.sample_cooperation_repository import SampleCooperationRepository
from erp_api.services.sample_cooperation_rules import (
    COOPERATION_ACTIVE_CREATOR_EVENT,
)


class _EmptyResult:
    def all(self):
        return []


class _Session:
    def __init__(self, database) -> None:
        self._database = database

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args) -> None:
        return None

    async def execute(self, statement):
        self._database.statement = statement
        return _EmptyResult()


class _Database:
    statement = None

    def system_session_factory(self):
        return _Session(self)


@pytest.mark.asyncio
async def test_candidates_exclude_historical_auto_assignments() -> None:
    database = _Database()
    repository = SampleCooperationRepository(
        database,
        activation_at=datetime(2026, 9, 1, tzinfo=UTC),
        batch_limit=100,
    )

    await repository.list_candidates(uuid4(), uuid4(), application_ids=None)

    sql = str(
        database.statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "bd_auto_assigned" in sql
    assert "erp_auto_assignment" in sql


@pytest.mark.asyncio
async def test_due_actions_include_daily_valid_creator_decisions() -> None:
    database = _Database()
    repository = SampleCooperationRepository(
        database,
        activation_at=datetime(2026, 9, 1, tzinfo=UTC),
        batch_limit=100,
    )

    await repository.list_due_actions(uuid4(), uuid4())

    sql = str(
        database.statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert COOPERATION_ACTIVE_CREATOR_EVENT in sql
