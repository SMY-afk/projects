from datetime import date
from uuid import uuid4

from erp_api.services.affiliate_center_contract import (
    AffiliateCenterQuery,
    AffiliateCenterResource,
)
from erp_api.services.affiliate_daily_queries import split_compass_queries


def test_compass_window_partition_uses_only_supported_sizes() -> None:
    query = AffiliateCenterQuery(
        shop_id=uuid4(),
        resource=AffiliateCenterResource.CREATORS,
        window_start=date(2026, 7, 1),
        window_end=date(2026, 8, 31),
        shop_timezone="America/Los_Angeles",
        currency="USD",
        filters={},
    )

    chunks = split_compass_queries(query)

    assert [(item.window_end - item.window_start).days + 1 for item in chunks] == [
        30,
        30,
        1,
        1,
    ]
    assert chunks[0].window_start == query.window_start
    assert chunks[-1].window_end == query.window_end
