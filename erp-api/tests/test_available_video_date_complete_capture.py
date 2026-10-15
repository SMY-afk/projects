from datetime import UTC, date, datetime
from uuid import uuid4

import pytest

from erp_api.services.affiliate_available_dates_repository import latest_available_dates


@pytest.mark.asyncio
async def test_later_complete_capture_is_not_capped_by_older_annotated_run():
    class Session:
        def __init__(self):
            self.values = iter(["America/Los_Angeles", date(2026, 10, 12),
                date(2026, 10, 9), datetime(2026, 10, 11, 7, tzinfo=UTC), date(2026, 10, 12)])

        async def scalar(self, query):
            return next(self.values)

    class Database:
        async def session(self, tenant):
            yield Session()

    result = await latest_available_dates(Database(), uuid4(), uuid4())
    assert result["videos"] == date(2026, 10, 10)
