from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import httpx

from erp_api.services.analytics_overview import build_overview_snapshots
from erp_api.services.tiktok_overview_client import HttpTikTokOverviewClient
from erp_api.services.tiktok_transport import TikTokTransport


def _transport(handler) -> TikTokTransport:
    return TikTokTransport(
        base_url="https://open.example.test",
        app_key="app-key",
        app_secret="app-secret",
        max_retries=0,
        http_transport=httpx.MockTransport(handler),
        clock=lambda: 1_700_000_000,
    )


def test_overview_client_requests_daily_video_metrics_and_parses_intervals() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "performance": {
                        "intervals": [
                            {
                                "start_date": "2026-08-01",
                                "end_date": "2026-08-02",
                                "gmv": {"amount": "12.34", "currency": "USD"},
                                "sku_orders": 3,
                                "product_clicks": 25,
                                "avg_customers": 2,
                                "click_through_rate": "0.125",
                            }
                        ]
                    },
                    "latest_available_date": "2026-08-01",
                },
                "request_id": "request-1",
            },
        )

    transport = _transport(handler)
    client = HttpTikTokOverviewClient(
        video_transport=transport,
        live_transport=transport,
        video_path="/analytics/202509/shop_videos/overview_performance",
        live_path="/analytics/202509/shop_lives/overview_performance",
    )

    result = asyncio.run(
        client.get_overview(
            "video",
            "access-token",
            shop_cipher="shop-cipher",
            start_date_ge="2026-08-01",
            end_date_lt="2026-08-02",
            currency="USD",
        )
    )

    assert requests[0].url.path == "/analytics/202509/shop_videos/overview_performance"
    assert requests[0].url.params["granularity"] == "1D"
    assert result.latest_available_date.isoformat() == "2026-08-01"
    assert result.intervals[0]["sku_orders"] == 3


def test_overview_snapshots_keep_video_and_live_metrics_separate() -> None:
    responses = {
        "video": {
            "start_date": "2026-08-01",
            "end_date": "2026-08-02",
            "gmv": {"amount": "12.34", "currency": "USD"},
            "sku_orders": 3,
            "product_clicks": 25,
            "avg_customers": 2,
            "click_through_rate": "12.5%",
        },
        "live": {
            "start_date": "2026-08-01",
            "end_date": "2026-08-02",
            "gmv": {"amount": "4.56", "currency": "USD"},
            "sku_orders": 1,
            "customers": 1,
            "click_to_order_rate": "0.25",
        },
    }

    video = build_overview_snapshots(
        "video",
        [responses["video"]],
        ZoneInfo("America/Los_Angeles"),
        platform_request_id="video-request",
    )[0]
    live = build_overview_snapshots(
        "live",
        [responses["live"]],
        ZoneInfo("America/Los_Angeles"),
        platform_request_id="live-request",
    )[0]

    assert video.window_start == datetime(2026, 8, 1, 7, tzinfo=UTC)
    assert video.metrics == {
        "videoGmv": {"amountMinor": 1234, "currency": "USD"},
        "videoOrders": 3,
        "videoProductClicks": 25,
        "videoAverageCustomers": 2,
        "videoClickThroughRate": 0.125,
    }
    assert live.metrics == {
        "liveGmv": {"amountMinor": 456, "currency": "USD"},
        "liveOrders": 1,
        "liveCustomers": 1,
        "liveClickToOrderRate": 0.25,
    }
