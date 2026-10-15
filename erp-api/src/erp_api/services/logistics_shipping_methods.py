"""Cache official shipping and fulfillment types together with package carriers."""
import asyncio
import json
import logging
from collections import defaultdict
from datetime import UTC, datetime

from erp_api.services.tiktok_order_carriers import carrier_name, names_by_package
from erp_api.services.tiktok_transport import TikTokClientError, tiktok_request_context

logger = logging.getLogger("erp_api.logistics_shipping_methods")


class LogisticsShippingMethods:
    def __init__(self, shops, orders, redis):
        self.shops, self.orders, self.redis = shops, orders, redis

    @staticmethod
    def key(tenant, order):
        return f"logistics:shipping-method:{tenant}:{order}"

    async def save(self, tenant, order, shipping_type, updated_at, fulfillments=(), *, fulfillment_type):
        payload = json.dumps({"shippingType": shipping_type, "versionEpoch": updated_at.timestamp(),
                              "checkedEpoch": datetime.now(UTC).timestamp(), "carrierVersion": 1,
                              "fulfillmentType": fulfillment_type, "methodVersion": 2,
                              "carrierNames": names_by_package(fulfillments)})
        script = """
        local prior = redis.call('get',KEYS[1]); local next = cjson.decode(ARGV[1])
        if prior then
          local old = cjson.decode(prior)
          if (old.versionEpoch or 0) > next.versionEpoch or
             ((old.versionEpoch or 0) == next.versionEpoch and (old.checkedEpoch or 0) > next.checkedEpoch) then return 0 end
        end
        return redis.call('set',KEYS[1],ARGV[1],'EX',ARGV[2])
        """
        return bool(await self.redis.eval(script, 1, self.key(tenant, order), payload, 120 * 86400))

    @staticmethod
    def apply(item, snapshot):
        item["shippingType"] = snapshot.get("shippingType")
        item["fulfillmentType"] = snapshot.get("fulfillmentType")
        carriers = snapshot.get("carrierNames", {})
        for package in item.get("packages", []):
            if not carrier_name(package.get("carrierName")):
                package["carrierName"] = carriers.get(package["packageId"])

    async def enrich(self, tenant, items, *, fetch_missing=True):
        if not items:
            return
        values = await self.redis.mget([self.key(tenant, item["id"]) for item in items])
        groups = defaultdict(list)
        for item, value in zip(items, values, strict=True):
            snapshot = json.loads(value) if value else {}
            self.apply(item, snapshot)
            missing_carrier = any(not carrier_name(package.get("carrierName")) for package in item.get("packages", []))
            if fetch_missing and (not value or snapshot.get("methodVersion") != 2
                                  or (missing_carrier and snapshot.get("carrierVersion") != 1)):
                groups[item["shopId"]].append(item)
        semaphore = asyncio.Semaphore(3)

        async def load(shop, rows):
            async with semaphore:
                try:
                    token = await self.shops.get_access_token(tenant, shop)
                    cipher = await self.shops.get_shop_cipher(tenant, shop)
                    if not token or not cipher:
                        raise RuntimeError("Shop authorization is unavailable")
                    for offset in range(0, len(rows), 20):
                        batch = rows[offset:offset + 20]
                        requested = {item["platformOrderId"]: item for item in batch}
                        with tiktok_request_context(tenant_id=str(tenant), shop_id=str(shop)):
                            orders = await self.orders.get_orders(token, shop_cipher=cipher, order_ids=list(requested))
                        identifiers = [o.platform_order_id for o in orders]
                        if len(set(identifiers)) != len(identifiers) or not set(identifiers) <= requested.keys():
                            raise ValueError("Shipping method order identity mismatch")
                        for order in orders:
                            item = requested[order.platform_order_id]
                            if await self.save(tenant, item["id"], order.shipping_type, order.platform_updated_at,
                                               order.fulfillments, fulfillment_type=order.fulfillment_type):
                                self.apply(item, {"shippingType": order.shipping_type, "fulfillmentType": order.fulfillment_type,
                                                  "carrierNames": names_by_package(order.fulfillments)})
                            else:
                                await self.enrich(tenant, [item], fetch_missing=False)
                except (RuntimeError, ValueError, TimeoutError, TikTokClientError) as error:
                    logger.warning("Shipping method API query failed: %s", type(error).__name__)
                    for item in rows:
                        await self.redis.set(self.key(tenant, item["id"]), json.dumps({"shippingType": None}), ex=60, nx=True)

        async def query(shop, rows):
            try:
                async with asyncio.timeout(8):
                    await load(shop, rows)
            except TimeoutError:
                logger.warning("Shipping method API query timed out")

        await asyncio.gather(*(query(shop, rows) for shop, rows in groups.items()))
