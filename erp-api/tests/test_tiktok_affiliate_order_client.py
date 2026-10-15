from __future__ import annotations

import asyncio

from erp_api.services.external_order_evidence import PLATFORM_NO_ORDER_LEVEL_EVIDENCE
from erp_api.services.tiktok_affiliate_order_client import (
    HttpTikTokAffiliateOrderClient,
    parse_affiliate_order_response,
)
from erp_api.services.tiktok_transport import TikTokRequest


class FakeTransport:
    def __init__(self, payload):
        self.payload = payload
        self.requests = []

    async def request(self, request: TikTokRequest, *, access_token: str):
        self.requests.append((request, access_token))
        return self.payload


def test_affiliate_order_matches_by_exact_order_id() -> None:
    transport = FakeTransport(
        {
            "data": {
                "orders": [
                    {
                        "order_id": "order-1",
                        "id": "conversion-1",
                        "creator_id": "creator-1",
                    }
                ]
            }
        }
    )
    signal = asyncio.run(
        HttpTikTokAffiliateOrderClient(transport).get_order_signal(
            "token",
            shop_cipher="cipher",
            platform_order_id="order-1",
            platform_order_item_ids=(),
        )
    )
    assert signal is not None
    assert signal.match_key_type == "order_id"
    assert signal.match_key == "order-1"
    assert signal.creator_external_id == "creator-1"
    assert transport.requests[0][0].query["order_id"] == "order-1"


def test_affiliate_order_matches_by_exact_order_item_id() -> None:
    transport = FakeTransport(
        {
            "data": {
                "items": [
                    {
                        "order_item_ids": ["item-1"],
                        "id": "conversion-1",
                        "creatorId": "creator-1",
                    }
                ]
            }
        }
    )
    signal = asyncio.run(
        HttpTikTokAffiliateOrderClient(transport).get_order_signal(
            "token",
            shop_cipher="cipher",
            platform_order_id="order-1",
            platform_order_item_ids=("item-1",),
        )
    )
    assert signal is not None
    assert signal.match_key_type == "order_item_id"
    assert signal.match_key == "item-1"


def test_affiliate_order_accepts_singular_order_item_id_field() -> None:
    records = parse_affiliate_order_response(
        {"data": {"orders": [{"orderItemId": "item-1", "id": "conversion-1"}]}}
    )
    assert records[0].platform_order_item_ids == ("item-1",)


def test_aggregate_record_without_exact_key_is_ignored() -> None:
    records = parse_affiliate_order_response(
        {
            "data": {
                "orders": [
                    {"creator_id": "creator-1", "id": "conversion-1"},
                    {"order_id": "order-1", "id": "conversion-2"},
                ]
            }
        }
    )
    assert len(records) == 1
    assert records[0].external_conversion_id == "conversion-2"


def test_affiliate_aggregate_rows_report_missing_order_level_evidence() -> None:
    transport = FakeTransport(
        {
            "data": {
                "orders": [
                    {
                        "creator_id": "creator-1",
                        "stat_time_day": "2026-08-13",
                        "gmv": "100.00",
                    }
                ]
            }
        }
    )
    result = asyncio.run(
        HttpTikTokAffiliateOrderClient(transport).lookup_order_evidence(
            "token",
            shop_cipher="cipher",
            platform_order_id="order-1",
            platform_order_item_ids=(),
        )
    )
    assert result.signal is None
    assert result.absence_reason == PLATFORM_NO_ORDER_LEVEL_EVIDENCE


def test_empty_affiliate_response_reports_missing_order_level_evidence() -> None:
    result = asyncio.run(
        HttpTikTokAffiliateOrderClient(
            FakeTransport({"data": {"orders": []}})
        ).lookup_order_evidence(
            "token",
            shop_cipher="cipher",
            platform_order_id="order-1",
            platform_order_item_ids=(),
        )
    )
    assert result.absence_reason == PLATFORM_NO_ORDER_LEVEL_EVIDENCE


def test_conflicting_order_id_cannot_match_by_order_item_id() -> None:
    transport = FakeTransport(
        {
            "data": {
                "orders": [
                    {
                        "order_id": "other-order",
                        "order_item_ids": ["item-1"],
                        "id": "conversion-1",
                    }
                ]
            }
        }
    )
    signal = asyncio.run(
        HttpTikTokAffiliateOrderClient(transport).get_order_signal(
            "token",
            shop_cipher="cipher",
            platform_order_id="order-1",
            platform_order_item_ids=("item-1",),
        )
    )
    assert signal is None


def test_exact_order_id_is_preferred_over_an_item_only_record() -> None:
    transport = FakeTransport(
        {
            "data": {
                "orders": [
                    {"order_item_ids": ["item-1"], "id": "item-conversion"},
                    {"order_id": "order-1", "id": "order-conversion"},
                ]
            }
        }
    )
    signal = asyncio.run(
        HttpTikTokAffiliateOrderClient(transport).get_order_signal(
            "token",
            shop_cipher="cipher",
            platform_order_id="order-1",
            platform_order_item_ids=("item-1",),
        )
    )
    assert signal is not None
    assert signal.match_key_type == "order_id"
    assert signal.external_conversion_id == "order-conversion"
