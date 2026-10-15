from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from erp_api.services.logistics_tracking_repository import LogisticsTrackingRepository


class _Result:
    def __init__(self, row):
        self._row = row

    def one_or_none(self):
        return self._row


class _Session:
    def __init__(self, row):
        self._row = row
        self.statement = None

    async def execute(self, statement):
        self.statement = statement
        return _Result(self._row)


@pytest.mark.asyncio
async def test_waybill_lookup_locks_only_waybill_table() -> None:
    waybill = SimpleNamespace(id=uuid4())
    session = _Session((waybill, {}))
    repository = LogisticsTrackingRepository(SimpleNamespace(), None)

    await repository._find_waybill(
        session,
        uuid4(),
        SimpleNamespace(external_waybill_id="package-1", tracking_number=None),
    )

    sql = str(
        session.statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": False},
        )
    )
    assert "FOR UPDATE OF logistics_waybills" in sql
