import asyncio
from datetime import date
from uuid import uuid4

import pytest

from backend.app.services.tiktok_affiliate_analytics_context import (
    AffiliateAnalyticsResponseContext,
)
from backend.app.services.tiktok_affiliate_creator_capture import (
    TikTokAffiliateCreatorCaptureSession,
)
from erp_api.services.affiliate_center_contract import (
    AffiliateCenterQuery,
    AffiliateCenterResource,
)
from erp_api.services.affiliate_center_source import AffiliateCenterPageDTO


class FakeReadRepository:
    def __init__(self, shop_id) -> None:
        self.shop_id = shop_id

    async def get_shop_context_by_platform_id(self, *_args):
        return {
            "shopId": self.shop_id,
            "shopTimezone": "America/Los_Angeles",
            "currency": "USD",
        }


class RejectWritesPersistence:
    def __init__(self) -> None:
        self.calls = []

    async def begin_capture(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        raise AssertionError("mismatched query must not start persistence")


def _payload() -> dict[str, object]:
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "segments": [
                {
                    "filter": {"shop_id": "platform-shop-1"},
                    "list_control": {
                        "next_pagination": {
                            "has_more": False,
                            "next_page": 2,
                            "total": 1,
                            "total_page": 1,
                        },
                        "rules": [],
                    },
                    "time_descriptor": {
                        "start": "2026-08-01T00:00:00",
                        "end": "2026-08-08T00:00:00",
                        "timezone_offset": -28800,
                    },
                    "timed_lists": [
                        {
                            "start": "2026-08-01",
                            "end": "2026-08-07",
                            "stats": [
                                {
                                    "id": "creator-1",
                                    "handle": "@creator",
                                    "revenue": {
                                        "amount": "12.34",
                                        "currency_code": "USD",
                                    },
                                    "order_cnt": 2,
                                }
                            ],
                        }
                    ],
                }
            ]
        },
    }


def _query(shop_id, *, window_start=date(2026, 8, 1)) -> AffiliateCenterQuery:
    return AffiliateCenterQuery(
        resource=AffiliateCenterResource.CREATORS,
        shop_id=shop_id,
        window_start=window_start,
        window_end=date(2026, 8, 7),
        shop_timezone="America/Los_Angeles",
        currency="USD",
        filters={},
    )


def test_matching_erp_query_is_mapped_to_the_shared_page_dto() -> None:
    shop_id = uuid4()
    session = TikTokAffiliateCreatorCaptureSession(
        uuid4(),
        FakeReadRepository(shop_id),  # type: ignore[arg-type]
        expected_query=_query(shop_id),
    )

    page = asyncio.run(
        session.build_page(
            _payload(),
            {"pagination": {"mode": "page_page_size"}},
            AffiliateAnalyticsResponseContext("platform-shop-1", "request-1"),
            1,
            None,
        )
    )

    assert type(page) is AffiliateCenterPageDTO
    assert page.query == _query(shop_id)
    assert page.records[0].affiliate_gmv_minor == 1234


def test_expected_query_accepts_plain_date_exclusive_end_from_routed_api() -> None:
    shop_id = uuid4()
    payload = _payload()
    payload["data"]["segments"][0]["time_descriptor"]["end"] = "2026-08-08"
    session = TikTokAffiliateCreatorCaptureSession(
        uuid4(),
        FakeReadRepository(shop_id),  # type: ignore[arg-type]
        expected_query=_query(shop_id),
    )

    page = asyncio.run(
        session.build_page(
            payload,
            {"pagination": {"mode": "page_page_size"}},
            AffiliateAnalyticsResponseContext("platform-shop-1", "request-1"),
            1,
            None,
        )
    )

    assert page.query.window_end == date(2026, 8, 7)


def test_mismatched_erp_window_stops_before_any_persistence() -> None:
    shop_id = uuid4()
    persistence = RejectWritesPersistence()
    session = TikTokAffiliateCreatorCaptureSession(
        uuid4(),
        FakeReadRepository(shop_id),  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        persistence,  # type: ignore[arg-type]
        expected_query=_query(shop_id, window_start=date(2026, 8, 2)),
    )

    with pytest.raises(ValueError, match="does not match the ERP request"):
        asyncio.run(
            session.persist_page(
                "creators",
                _payload(),
                {},
                AffiliateAnalyticsResponseContext("platform-shop-1", "request-1"),
                1,
                None,
            )
        )

    assert persistence.calls == []
