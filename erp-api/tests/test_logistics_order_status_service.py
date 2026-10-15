from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from erp_api.services.logistics_order_status_service import LogisticsOrderStatusService


@pytest.mark.asyncio
@pytest.mark.parametrize("package_carrier", ["Carrier", None, " "])
async def test_refresh_reads_only_selected_order_from_official_api(package_carrier) -> None:
    order_id = uuid4()
    tenant_id = uuid4()
    shop_id = uuid4()
    calls = []

    class Repository:
        async def get_synced_at(self, current_tenant, current_order):
            assert (current_tenant, current_order) == (tenant_id, order_id)
            return datetime(2026, 10, 12, tzinfo=UTC)

        async def get_target(self, current_tenant, current_order):
            assert (current_tenant, current_order) == (tenant_id, order_id)
            return {
                "shop_id": shop_id,
                "platform_order_id": "platform-order-1",
                "platform_package_ids": ("package-1", "package-2"),
                "placed_at": datetime(2026, 10, 7, tzinfo=UTC),
            }

    class Shops:
        async def get_access_token(self, *_):
            return "token"

        async def get_shop_cipher(self, *_):
            return "cipher"

    class Client:
        async def get_tracking(self, token, *, shop_cipher, order_id):
            calls.append(("tracking", token, shop_cipher, order_id))
            return [
                SimpleNamespace(
                    normalized_status="delivered",
                    occurred_at=datetime(2026, 10, 12, 1, tzinfo=UTC),
                    action_code="50101",
                    sequence_no=1,
                    description="Delivered",
                )
            ]

        async def get_package_detail(self, token, *, shop_cipher, package_id):
            calls.append(("package", token, shop_cipher, package_id))
            return SimpleNamespace(
                package_id=package_id,
                package_status="COMPLETED",
                carrier_name=package_carrier,
                tracking_number="1234567890",
            )

    class Orders:
        async def get_order(self, token, *, shop_cipher, order_id):
            calls.append(("order", token, shop_cipher, order_id))
            return SimpleNamespace(
                platform_order_id=order_id,
                external_status="COMPLETED",
                shipping_type="TIKTOK",
                fulfillment_type="FULFILLMENT_BY_TIKTOK",
                placed_at=datetime(2026, 10, 7, 1, tzinfo=UTC),
                platform_updated_at=datetime(2026, 10, 12, tzinfo=UTC),
                fulfillments=[
                    SimpleNamespace(platform_package_id=value, carrier=carrier)
                    for value, carrier in [("package-1", "USPS"), ("package-2", "FedEx")]
                ],
            )

    service = LogisticsOrderStatusService(Repository(), Shops(), Client(), Orders())
    result = await service.refresh(tenant_id, order_id)

    assert result["trackingStatus"] == "delivered"
    assert result["platformStatus"] == "COMPLETED"
    assert result["shippingType"] == "TIKTOK"
    assert result["fulfillmentType"] == "FULFILLMENT_BY_TIKTOK"
    assert result["orderCreatedAt"] == datetime(2026, 10, 7, tzinfo=UTC)
    assert len(result["events"]) == 1
    assert [item["packageId"] for item in result["packages"]] == [
        "package-1",
        "package-2",
    ]
    assert all(
        item["trackingNumberMasked"] == "******7890" for item in result["packages"]
    )
    assert [item["carrierName"] for item in result["packages"]] == (
        ["Carrier", "Carrier"] if package_carrier == "Carrier" else ["USPS", "FedEx"]
    )
    assert calls == [
        ("order", "token", "cipher", "platform-order-1"),
        ("tracking", "token", "cipher", "platform-order-1"),
        ("package", "token", "cipher", "package-1"),
        ("package", "token", "cipher", "package-2"),
    ]


@pytest.mark.asyncio
async def test_list_and_export_forward_the_same_order_and_shop_filter() -> None:
    tenant_id, shop_id = uuid4(), uuid4()
    calls = []

    class Repository:
        async def list_orders(self, tenant, **params):
            calls.append((tenant, params))
            return {"items": [], "total": 0}

    service = LogisticsOrderStatusService(Repository(), None, None, None)
    await service.list_orders(
        tenant_id,
        page=2,
        page_size=20,
        shop_id=shop_id,
        order_number="982740775181726442",
    )
    await service.export_orders(tenant_id, shop_id, "982740775181726442")
    assert calls == [
        (
            tenant_id,
            {
                "page": 2,
                "page_size": 20,
                "shop_id": shop_id,
                "order_number": "982740775181726442",
                "category": None,
                "alert": None,
                "alert_phase": "overdue",
            },
        ),
        (
            tenant_id,
            {
                "page": 1,
                "page_size": 100_000,
                "shop_id": shop_id,
                "order_number": "982740775181726442",
                "snapshot": True,
                "category": None,
                "alert": None,
                "alert_phase": "overdue",
            },
        ),
    ]
