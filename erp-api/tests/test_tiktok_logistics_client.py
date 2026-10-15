from datetime import UTC, datetime

import httpx
import pytest

from erp_api.services.tiktok_logistics_client import (
    HttpTikTokLogisticsClient,
    parse_package_detail,
    parse_tracking_events,
)
from erp_api.services.tiktok_transport import TikTokTransport


def test_parses_real_package_detail_fields_without_inventing_tracking() -> None:
    detail = parse_package_detail(
        {
            "code": 0,
            "data": {
                "package_id": "pkg-1",
                "package_status": "FULFILLING",
                "shipping_provider_id": "provider-1",
                "shipping_provider_name": "USPS",
                "delivery_option_id": "option-1",
                "shipping_type": "TIKTOK",
                "tracking_number": "9977650080159121307114",
                "order_line_item_ids": ["line-1", "line-2"],
                "update_time": 1_787_625_685,
                "weight": {"value": "1.25", "unit": "KILOGRAM"},
                "dimension": {
                    "length": "10",
                    "width": "8",
                    "height": "4",
                    "unit": "INCH",
                },
            },
        }
    )

    assert detail.package_id == "pkg-1"
    assert detail.platform_carrier_id == "provider-1"
    assert detail.tracking_number == "9977650080159121307114"
    assert detail.order_line_item_ids == ("line-1", "line-2")
    assert detail.updated_at == datetime.fromtimestamp(1_787_625_685, UTC)
    assert detail.weight_grams == 1_250
    assert (detail.length_mm, detail.width_mm, detail.height_mm) == (254, 203, 102)

    missing = parse_package_detail(
        {
            "code": 0,
            "data": {"package_id": "pkg-2", "package_status": "AWAITING_COLLECTION"},
        }
    )
    assert missing.tracking_number is None


def test_parses_tracking_in_chronological_order_and_maps_action_codes() -> None:
    events = parse_tracking_events(
        {
            "code": 0,
            "data": {
                "tracking": [
                    {
                        "action_code": 50101,
                        "update_time_millis": 2_000,
                        "description": "Delivered",
                    },
                    {
                        "action_code": 41501,
                        "update_time_millis": 1_000,
                        "description": "In transit",
                    },
                ]
            },
        }
    )

    assert [event.normalized_status for event in events] == ["in_transit", "delivered"]
    assert [event.occurred_at.timestamp() for event in events] == [1.0, 2.0]


@pytest.mark.parametrize(
    ("code", "description", "expected"),
    [
        ("500901", "Package is being prepared at warehouse.", "info_received"),
        ("500999", None, "info_received"),
        ("50101", "Package was not delivered. Delivery failed.", "exception"),
        ("50101", "Package returned to sender.", "returned"),
        ("30901", "Your package was delivered!", "delivered"),
        ("20101", "Order packed and ready for pickup.", "info_received"),
        ("21001", "Package details received by the carrier.", "info_received"),
        ("unknown", "Package picked up and currently at CHINO.", "picked_up"),
    ],
)
def test_completed_nodes_require_actual_delivery_or_collection_evidence(
    code, description, expected
):
    events = parse_tracking_events(
        {
            "data": {
                "tracking": [
                    {
                        "action_code": code,
                        "update_time_millis": 1000,
                        "description": description,
                    }
                ]
            }
        }
    )
    assert events[0].normalized_status == expected


def test_prefers_known_machine_readable_event_name_when_present():
    events = parse_tracking_events({'data': {'tracking': [{
        'action_code': 30901, 'action_code_name': 'pickup_success',
        'update_time_millis': 1000, 'description': '包裹已被揽收',
    }]}})
    assert events[0].normalized_status == 'picked_up'


@pytest.mark.asyncio
async def test_http_client_uses_official_package_and_tracking_paths() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/tracking"):
            return httpx.Response(200, json={"code": 0, "data": {"tracking": []}})
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {"package_id": "pkg-1", "package_status": "FULFILLING"},
            },
        )

    transport = TikTokTransport(
        base_url="https://open-api.tiktokglobalshop.com",
        app_key="app-key",
        app_secret="app-secret",
        http_transport=httpx.MockTransport(handler),
    )
    client = HttpTikTokLogisticsClient(transport)

    await client.get_package_detail("token", shop_cipher="cipher", package_id="pkg-1")
    await client.get_tracking("token", shop_cipher="cipher", order_id="order-1")

    assert [request.url.path for request in requests] == [
        "/fulfillment/202309/packages/pkg-1",
        "/fulfillment/202309/orders/order-1/tracking",
    ]
    assert all(request.url.params["shop_cipher"] == "cipher" for request in requests)
