from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from erp_api.services.tiktok_order_schemas import parse_order


def test_order_parser_reads_actual_shipping_type_and_does_not_infer_from_fulfillment():
    raw = {"id": "100", "status": "AWAITING_SHIPMENT", "create_time": 1_700_000_000,
           "update_time": 1_700_000_100, "shipping_type": "TIKTOK", "fulfillment_type": "FULFILLMENT_BY_SELLER"}
    assert parse_order(raw).shipping_type == "TIKTOK"
    assert parse_order(raw).fulfillment_type == "FULFILLMENT_BY_SELLER"
    raw.pop("shipping_type")
    assert parse_order(raw).shipping_type is None


@pytest.mark.asyncio
async def test_page_batches_by_shop_and_keeps_unknown_shipping_types_unknown():
    from erp_api.services.logistics_shipping_methods import LogisticsShippingMethods

    tenant, first, second = uuid4(), uuid4(), uuid4()
    rows = [{"id": uuid4(), "shopId": shop, "platformOrderId": number}
            for shop, number in [(first, "100"), (first, "101"), (second, "102")]]
    redis = SimpleNamespace(mget=AsyncMock(return_value=[None] * 3), eval=AsyncMock(), set=AsyncMock())
    shops = SimpleNamespace(get_access_token=AsyncMock(return_value="token"), get_shop_cipher=AsyncMock(return_value="cipher"))
    orders = SimpleNamespace(get_orders=AsyncMock(side_effect=[[
        SimpleNamespace(platform_order_id="100", shipping_type="SELLER", fulfillment_type="FULFILLMENT_BY_SELLER", platform_updated_at=datetime.now(UTC), fulfillments=[]),
        SimpleNamespace(platform_order_id="101", shipping_type=None, fulfillment_type=None, platform_updated_at=datetime.now(UTC), fulfillments=[]),
    ], [SimpleNamespace(platform_order_id="102", shipping_type="TIKTOK", fulfillment_type="FULFILLMENT_BY_TIKTOK", platform_updated_at=datetime.now(UTC), fulfillments=[])]]))
    await LogisticsShippingMethods(shops, orders, redis).enrich(tenant, rows)
    assert [r["shippingType"] for r in rows] == ["SELLER", None, "TIKTOK"]
    assert [r["fulfillmentType"] for r in rows] == ["FULFILLMENT_BY_SELLER", None, "FULFILLMENT_BY_TIKTOK"]
    assert orders.get_orders.await_count == 2
    assert redis.eval.await_count == 3


@pytest.mark.asyncio
async def test_wrong_order_response_cannot_fill_another_orders_shipping_method():
    from erp_api.services.logistics_shipping_methods import LogisticsShippingMethods

    redis = SimpleNamespace(mget=AsyncMock(return_value=[None]), eval=AsyncMock(), set=AsyncMock())
    shops = SimpleNamespace(get_access_token=AsyncMock(return_value="token"), get_shop_cipher=AsyncMock(return_value="cipher"))
    orders = SimpleNamespace(get_orders=AsyncMock(return_value=[SimpleNamespace(
        platform_order_id="other", shipping_type="SELLER", platform_updated_at=datetime.now(UTC))]))
    rows = [{"id": uuid4(), "shopId": uuid4(), "platformOrderId": "100"}]
    await LogisticsShippingMethods(shops, orders, redis).enrich(uuid4(), rows)
    assert rows[0]["shippingType"] is None
    redis.eval.assert_not_awaited()


@pytest.mark.asyncio
async def test_cached_page_and_export_do_not_make_extra_official_requests():
    import json

    from erp_api.services.logistics_shipping_methods import LogisticsShippingMethods

    orders = SimpleNamespace(get_orders=AsyncMock())
    redis = SimpleNamespace(mget=AsyncMock(return_value=[json.dumps({"shippingType": "SELLER"})]))
    rows = [{"id": uuid4(), "shopId": uuid4(), "platformOrderId": "100"}]
    await LogisticsShippingMethods(None, orders, redis).enrich(uuid4(), rows, fetch_missing=False)
    assert rows[0]["shippingType"] == "SELLER"
    orders.get_orders.assert_not_awaited()
