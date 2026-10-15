from __future__ import annotations

import asyncio

from erp_api.services.external_order_evidence import PLATFORM_NO_ORDER_LEVEL_EVIDENCE
from erp_api.services.tiktok_ads_order_client import HttpTikTokAdsOrderClient
from erp_api.services.tiktok_transport import TikTokRequest


class FakeTransport:
    def __init__(self, payload):
        self.payload = payload
        self.requests = []

    async def request(self, request: TikTokRequest, *, access_token: str):
        self.requests.append((request, access_token))
        return self.payload


def test_ads_client_matches_exact_order_id() -> None:
    transport = FakeTransport(
        {
            "data": {
                "conversions": [
                    {
                        "order_id": "order-1",
                        "conversion_id": "ads-conversion-1",
                        "campaign_id": "campaign-1",
                    }
                ]
            }
        }
    )
    signal = asyncio.run(
        HttpTikTokAdsOrderClient(transport).get_order_signal(
            "token",
            shop_cipher="cipher",
            platform_order_id="order-1",
            platform_order_item_ids=(),
        )
    )
    assert signal is not None
    assert signal.match_key_type == "order_id"
    assert signal.campaign_external_id == "campaign-1"


def test_ads_client_does_not_match_conflicting_order_id_by_item_id() -> None:
    transport = FakeTransport(
        {
            "data": {
                "conversions": [
                    {
                        "order_id": "other-order",
                        "order_item_ids": ["item-1"],
                        "conversion_id": "conversion-1",
                    }
                ]
            }
        }
    )
    signal = asyncio.run(
        HttpTikTokAdsOrderClient(transport).get_order_signal(
            "token",
            shop_cipher="cipher",
            platform_order_id="order-1",
            platform_order_item_ids=("item-1",),
        )
    )
    assert signal is None


def test_ads_report_row_with_generic_id_is_not_order_level_evidence() -> None:
    transport = FakeTransport(
        {
            "data": {
                "conversions": [
                    {
                        "order_id": "order-1",
                        "id": "report-row-1",
                        "campaign_id": "campaign-1",
                    }
                ]
            }
        }
    )
    signal = asyncio.run(
        HttpTikTokAdsOrderClient(transport).get_order_signal(
            "token",
            shop_cipher="cipher",
            platform_order_id="order-1",
            platform_order_item_ids=(),
        )
    )
    assert signal is None


def test_ads_aggregate_rows_report_missing_order_level_evidence() -> None:
    transport = FakeTransport(
        {
            "data": {
                "conversions": [
                    {
                        "campaign_id": "campaign-1",
                        "stat_time_day": "2026-08-13",
                        "spend": "10.00",
                    }
                ]
            }
        }
    )
    result = asyncio.run(
        HttpTikTokAdsOrderClient(transport).lookup_order_evidence(
            "token",
            shop_cipher="cipher",
            platform_order_id="order-1",
            platform_order_item_ids=(),
        )
    )
    assert result.signal is None
    assert result.absence_reason == PLATFORM_NO_ORDER_LEVEL_EVIDENCE


def test_empty_ads_response_reports_missing_order_level_evidence() -> None:
    result = asyncio.run(
        HttpTikTokAdsOrderClient(
            FakeTransport({"data": {"conversions": []}})
        ).lookup_order_evidence(
            "token",
            shop_cipher="cipher",
            platform_order_id="order-1",
            platform_order_item_ids=(),
        )
    )
    assert result.absence_reason == PLATFORM_NO_ORDER_LEVEL_EVIDENCE
