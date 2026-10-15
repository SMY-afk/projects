from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

import pytest

from erp_api.services.affiliate_center_contract import (
    AffiliateCenterQuery,
    AffiliateCenterResource,
)
from erp_api.services.affiliate_center_metric_dtos import AffiliateCreatorMetricDTO
from erp_api.services.affiliate_creator_metric_parser import (
    AffiliateCreatorMetricParseError,
    parse_creator_official_rows,
    parse_creator_page_payload,
)


def _page_payload() -> dict[str, object]:
    return {
        "code": 0,
        "message": "ok",
        "data": {
            "segments": [
                {
                    "filter": {"shop_id": "shop-1"},
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
                        "start": "2026-08-01",
                        "end": "2026-08-07",
                        "timezone_offset": -7,
                    },
                    "timed_lists": [
                        {
                            "start": "2026-08-01",
                            "end": "2026-08-07",
                            "stats": [
                                {
                                    "id": "creator-1",
                                    "handle": "@Creator",
                                    "revenue": {
                                        "amount": "1,234.50",
                                        "currency_code": "USD",
                                    },
                                    "live_revenue": {
                                        "amount": "0",
                                        "currency_code": "USD",
                                    },
                                    "video_revenue": {
                                        "amount": "1,234.50",
                                        "currency_code": "USD",
                                    },
                                    "product_card_revenue": {
                                        "amount": "0",
                                        "currency_code": "USD",
                                    },
                                    "est_commission": {
                                        "amount": "123.45",
                                        "currency_code": "USD",
                                    },
                                    "aov": {
                                        "amount": "88.43",
                                        "currency_code": "USD",
                                    },
                                    "refund_revenue": {
                                        "amount": "34.80",
                                        "currency_code": "USD",
                                    },
                                    "item_sold": "1.2K",
                                    "refund_item_sold": "2",
                                    "order_cnt": "9",
                                    "product_impression": "13,988",
                                    "ctr": "5.67%",
                                    "product_cnt": "4",
                                    "buyer_cnt_daily_avg": "1.29",
                                    "live_cnt": "0",
                                    "video_cnt": "4",
                                    "follow_cnt": "25K",
                                    "unverified_metric": {
                                        "value": "7",
                                        "email": "private@example.test",
                                    },
                                    "message": "private message",
                                }
                            ],
                        }
                    ],
                }
            ]
        },
    }


def _query(currency: str = "USD") -> AffiliateCenterQuery:
    return AffiliateCenterQuery(
        resource=AffiliateCenterResource.CREATORS,
        shop_id=UUID("e4408786-af60-545e-8f8c-5ef22a71e675"),
        window_start=date(2026, 8, 1),
        window_end=date(2026, 8, 7),
        shop_timezone="America/Los_Angeles",
        currency=currency,
        filters={},
    )


def test_creator_page_payload_maps_to_domain_dto() -> None:
    result = parse_creator_page_payload(_page_payload(), query=_query())

    assert result == [
        AffiliateCreatorMetricDTO(
            username="@Creator",
            username_normalized="creator",
            window_start_utc=datetime(2026, 8, 1, 7, tzinfo=UTC),
            window_end_utc=datetime(2026, 8, 8, 7, tzinfo=UTC),
            shop_timezone="America/Los_Angeles",
            currency="USD",
            source_identifiers={"tiktok_page_creator_id": "creator-1"},
            affiliate_gmv_minor=123450,
            affiliate_live_gmv_minor=0,
            affiliate_video_gmv_minor=123450,
            affiliate_showcase_gmv_minor=0,
            items_sold=1200,
            estimated_commission_minor=12345,
            average_order_amount_minor=8843,
            showcase_product_count=4,
            affiliate_order_count=9,
            click_through_rate="0.0567",
            product_impressions=13988,
            average_affiliate_customers=Decimal("1.29"),
            affiliate_live_count=0,
            affiliate_video_count=4,
            refunded_affiliate_gmv_minor=3480,
            refunded_affiliate_product_count=2,
            affiliate_follower_count=25000,
            extensions={"unverified_metric": {"value": "7"}},
        )
    ]


def test_creator_official_rows_map_stable_identifiers_and_extensions() -> None:
    official = parse_creator_official_rows(
        [
            {
                "creatorId": "creator-1",
                "creatorOpenId": "open-1",
                "creator_id": "similar-name-must-not-map",
                "username": "@Creator",
                "currency": "USD",
                "affiliateGmvMinor": "123450",
                "affiliateOrderCount": "9",
                "clickThroughRate": "0.0567",
                "unconfirmed": {"value": 1, "phone": "private"},
            }
        ],
        query=_query(),
    )[0]
    assert isinstance(official, AffiliateCreatorMetricDTO)
    assert official.affiliate_gmv_minor == 123450
    assert official.affiliate_order_count == 9
    assert official.click_through_rate == "0.0567"
    assert isinstance(official.affiliate_gmv_minor, int)
    assert official.creator_open_id == "open-1"
    assert official.source_identifiers == {"official_creator_id": "creator-1"}
    assert official.extensions == {
        "creator_id": "similar-name-must-not-map",
        "unconfirmed": {"value": 1},
    }


def test_creator_official_rows_preserve_click_rates_above_one() -> None:
    official = parse_creator_official_rows(
        [
            {
                "creatorId": "creator-1",
                "username": "@Creator",
                "currency": "USD",
                "clickThroughRate": "1.255",
            }
        ],
        query=_query(),
    )[0]

    assert official.click_through_rate == "1.255"


def test_creator_page_rejects_query_currency_mismatch() -> None:
    with pytest.raises(AffiliateCreatorMetricParseError, match="currency"):
        parse_creator_page_payload(_page_payload(), query=_query("EUR"))


def test_creator_page_rejects_float_money_input() -> None:
    payload = _page_payload()
    stat = payload["data"]["segments"][0]["timed_lists"][0]["stats"][0]
    stat["revenue"]["amount"] = 12.34

    with pytest.raises(AffiliateCreatorMetricParseError, match="float"):
        parse_creator_page_payload(payload, query=_query())


def test_creator_page_uses_private_id_for_stable_anonymous_username() -> None:
    payload = _page_payload()
    stat = payload["data"]["segments"][0]["timed_lists"][0]["stats"][0]
    stat["handle"] = None

    first = parse_creator_page_payload(payload, query=_query())[0]
    second = parse_creator_page_payload(payload, query=_query())[0]

    assert first.username == second.username
    assert first.username.startswith("@unknown_")
    assert first.username_normalized == first.username.lstrip("@")
    assert first.creator_open_id is None
    assert first.source_identifiers == {"tiktok_page_creator_id": "creator-1"}
    assert first.extensions["identity"] == {"usernameMissing": True}
