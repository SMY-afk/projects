import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from erp_api.services.logistics_shipping_methods import LogisticsShippingMethods


@pytest.mark.asyncio
async def test_cached_order_carriers_only_fill_missing_matching_package_names():
    orders = SimpleNamespace(get_orders=AsyncMock())
    redis = SimpleNamespace(mget=AsyncMock(return_value=[json.dumps({
        "shippingType": "TIKTOK", "carrierVersion": 1, "methodVersion": 2,
        "fulfillmentType": "FULFILLMENT_BY_TIKTOK",
        "carrierNames": {"p1": "USPS", "p2": "FedEx"},
    })]))
    rows = [{"id": uuid4(), "shopId": uuid4(), "platformOrderId": "order-1", "packages": [
        {"packageId": "p1", "carrierName": None},
        {"packageId": "p2", "carrierName": "Official Package Carrier"},
        {"packageId": "p3", "carrierName": None},
    ]}]
    await LogisticsShippingMethods(None, orders, redis).enrich(uuid4(), rows)
    assert [p["carrierName"] for p in rows[0]["packages"]] == ["USPS", "Official Package Carrier", None]
    assert rows[0]["fulfillmentType"] == "FULFILLMENT_BY_TIKTOK"
    orders.get_orders.assert_not_awaited()


@pytest.mark.asyncio
async def test_old_shipping_cache_fetches_order_metadata_without_changing_query_or_sync_times():
    now = datetime.now(UTC)
    redis = SimpleNamespace(mget=AsyncMock(return_value=[json.dumps({"shippingType": "SELLER"})]),
                            eval=AsyncMock(return_value=1), set=AsyncMock())
    shops = SimpleNamespace(get_access_token=AsyncMock(return_value="token"),
                            get_shop_cipher=AsyncMock(return_value="cipher"))
    orders = SimpleNamespace(get_orders=AsyncMock(return_value=[SimpleNamespace(
        platform_order_id="order-1", shipping_type="SELLER", fulfillment_type="FULFILLMENT_BY_SELLER", platform_updated_at=now,
        fulfillments=[SimpleNamespace(platform_package_id="p1", carrier="FedEx")],
    )]))
    rows = [{"id": uuid4(), "shopId": uuid4(), "platformOrderId": "order-1",
             "officialCheckedAt": "query-before", "erpSyncedAt": "sync-before",
             "packages": [{"packageId": "p1", "carrierName": None}]}]
    await LogisticsShippingMethods(shops, orders, redis).enrich(uuid4(), rows)
    assert rows[0]["packages"][0]["carrierName"] == "FedEx"
    assert rows[0]["officialCheckedAt"] == "query-before"
    assert rows[0]["erpSyncedAt"] == "sync-before"
    orders.get_orders.assert_awaited_once()
    cached = json.loads(redis.eval.call_args.args[3])
    assert cached["carrierVersion"] == 1 and cached["carrierNames"] == {"p1": "FedEx"}
    assert cached["fulfillmentType"] == "FULFILLMENT_BY_SELLER" and cached["methodVersion"] == 2
