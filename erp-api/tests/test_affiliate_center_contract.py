from datetime import UTC, date, datetime
from uuid import uuid4

import pytest

from erp_api.services.affiliate_center_contract import (
    AffiliateCenterQuery,
    AffiliateCenterQueryError,
    AffiliateCenterResource,
)


def _query(**changes) -> AffiliateCenterQuery:
    values = {
        "resource": AffiliateCenterResource.CREATORS,
        "shop_id": uuid4(),
        "window_start": date(2026, 7, 6),
        "window_end": date(2026, 7, 12),
        "shop_timezone": "America/Los_Angeles",
        "currency": "usd",
        "filters": {"collaborationType": "all", "tiers": [3, 1]},
    }
    return AffiliateCenterQuery(**(values | changes))


def test_resources_are_frozen_as_creators_and_videos() -> None:
    assert {resource.value for resource in AffiliateCenterResource} == {
        "creators",
        "videos",
    }


def test_query_canonicalizes_currency_filters_and_fingerprint() -> None:
    shop_id = uuid4()
    first = _query(shop_id=shop_id, filters={"b": 2, "a": 1})
    second = _query(shop_id=shop_id, filters={"a": 1, "b": 2})

    assert first.currency == "USD"
    assert first.canonical_dimensions() == {
        "shopId": str(shop_id),
        "windowStart": "2026-07-06",
        "windowEnd": "2026-07-12",
        "shopTimezone": "America/Los_Angeles",
        "currency": "USD",
        "filters": {"a": 1, "b": 2},
    }
    assert first.fingerprint == second.fingerprint
    assert (
        first.with_resource(AffiliateCenterResource.VIDEOS).fingerprint
        != first.fingerprint
    )


def test_local_inclusive_dates_convert_to_dst_safe_utc_half_open_window() -> None:
    query = _query(
        window_start=date(2026, 3, 8),
        window_end=date(2026, 3, 8),
    )

    assert query.utc_window() == (
        datetime(2026, 3, 8, 8, tzinfo=UTC),
        datetime(2026, 3, 9, 7, tzinfo=UTC),
    )


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"window_end": date(2026, 7, 5)}, "结束日期"),
        ({"shop_timezone": "GMT-08:00"}, "IANA"),
        ({"currency": "US"}, "币种"),
        ({"filters": {"accessToken": "secret"}}, "敏感"),
        ({"filters": ["not-an-object"]}, "对象"),
    ],
)
def test_query_rejects_invalid_dimensions(changes, message: str) -> None:
    with pytest.raises(AffiliateCenterQueryError, match=message):
        _query(**changes)
