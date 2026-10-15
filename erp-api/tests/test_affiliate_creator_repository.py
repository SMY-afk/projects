import asyncio
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from erp_api.services.affiliate_creator_repository import (
    AffiliateCreatorRepository,
)


class FakeDatabase:
    def __init__(self, session) -> None:
        self.session_value = session

    async def session(self, tenant_id):
        yield self.session_value


class ReportListSession:
    def __init__(self) -> None:
        self.statement = None

    async def scalars(self, statement):
        self.statement = statement
        return []


def _sql(statement) -> str:
    return str(statement.compile(dialect=postgresql.dialect()))


def test_report_listing_prioritizes_complete_snapshots_over_partial_runs() -> None:
    session = ReportListSession()
    repository = AffiliateCreatorRepository(FakeDatabase(session))

    assert asyncio.run(repository.list_reports(uuid4(), uuid4())) == []

    sql = _sql(session.statement)
    assert "CASE WHEN (affiliate_creator_reports.status =" in sql
    assert "affiliate_creator_reports.period_end DESC" in sql
