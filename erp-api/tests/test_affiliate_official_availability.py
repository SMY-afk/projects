from datetime import date
from uuid import uuid4

import pytest

from erp_api.services.affiliate_official_availability import (
    AffiliateOfficialAvailabilityRepository,
)


class FakeRedis:
    def __init__(self, value):
        self.value = value

    async def get(self, _key):
        return self.value


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["2026-08-30", b"2026-08-30"])
async def test_latest_official_date_accepts_string_and_bytes(value) -> None:
    repository = AffiliateOfficialAvailabilityRepository(FakeRedis(value))
    assert await repository.get(uuid4(), uuid4()) == date(2026, 8, 30)
