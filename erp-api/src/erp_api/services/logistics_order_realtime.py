"""Cache official logistics queries independently of background order synchronization."""

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from erp_api.models.order_sync import OrderSyncRun
from erp_api.models.shop import Shop
from erp_api.services.tiktok_transport import TikTokClientError


class LogisticsOrderRealtime:
    def __init__(self, sync_service, database, redis):
        self.sync_service, self.database, self.redis = sync_service, database, redis

    @staticmethod
    def cache_key(tenant, order):
        return f"logistics:official-status:{tenant}:{order}"

    async def cached(self, tenant, orders):
        if not orders:
            return {}
        values = await self.redis.mget(
            [self.cache_key(tenant, order) for order in orders]
        )
        return {
            order: read_snapshot(value)
            for order, value in zip(orders, values, strict=True)
            if value
        }

    async def save(self, tenant, order, result):
        payload = {
            name: result[name]
            for name in (
                "checkedAt",
                "deliveredAt",
                "trackingStatus",
                "platformUpdatedAt",
                "packages",
                "firstLocationAt",
                "shippedAt",
                "collectedAt",
            )
        }
        key = self.cache_key(tenant, order)
        payload["versionEpoch"] = result["platformUpdatedAt"].timestamp()
        payload["queriedEpoch"] = result["checkedAt"].timestamp()
        payload["ruleVersion"] = 2
        script = """
        local prior = redis.call('get',KEYS[1]); local next = cjson.decode(ARGV[1]); local encoded = ARGV[1]
        if prior then
          local old = cjson.decode(prior)
          if (old.versionEpoch or 0) > next.versionEpoch or
             ((old.versionEpoch or 0) == next.versionEpoch and (old.queriedEpoch or 0) > next.queriedEpoch) then return 0 end
          for _, field in ipairs({'deliveredAt', 'firstLocationAt', 'collectedAt', 'shippedAt'}) do
            if old.ruleVersion == 2 and next[field] == cjson.null and old[field] ~= nil and old[field] ~= cjson.null then
              encoded = string.gsub(encoded, '"'..field..'": null', '"'..field..'": '..cjson.encode(old[field]), 1)
            end
          end
        end
        return redis.call('set',KEYS[1],encoded,'EX',ARGV[2])
        """
        await self.redis.eval(
            script,
            1,
            key,
            json.dumps(payload, default=lambda value: value.isoformat()),
            120 * 86400,
        )

    async def sync_shops(self, tenant, selected_shop):
        async with self.database.system_session_factory() as session:
            conditions = [
                Shop.tenant_id == tenant,
                Shop.platform == "tiktok",
                Shop.status == "active",
            ]
            if selected_shop:
                conditions.append(Shop.id == selected_shop)
            shops = list(await session.scalars(select(Shop.id).where(*conditions)))
        results = []
        for shop in shops:
            cursor = await self.sync_service._repository.get_cursor(tenant, shop)
            if cursor.last_success_at and datetime.now(
                UTC
            ) - cursor.last_success_at < timedelta(seconds=50):
                results.append(
                    {
                        "shopId": str(shop),
                        "status": "current",
                        "syncedAt": cursor.last_success_at,
                    }
                )
                continue
            lock = f"logistics:order-sync-lock:{tenant}:{shop}"
            owner = str(uuid4())
            acquired = await self.redis.set(lock, owner, nx=True, ex=300)
            if not acquired:
                results.append(
                    {
                        "shopId": str(shop),
                        "status": "syncing",
                        "syncedAt": cursor.last_success_at,
                    }
                )
                continue
            try:
                async with self.database.system_session_factory() as session:
                    active = await session.scalar(
                        select(OrderSyncRun.id).where(
                            OrderSyncRun.tenant_id == tenant,
                            OrderSyncRun.shop_id == shop,
                            OrderSyncRun.status == "running",
                        )
                    )
                if active:
                    results.append(
                        {
                            "shopId": str(shop),
                            "status": "syncing",
                            "syncedAt": cursor.last_success_at,
                        }
                    )
                    continue
                end = datetime.now(UTC)
                start = (
                    cursor.last_success_at - timedelta(minutes=1)
                    if cursor.last_success_at
                    else end - timedelta(days=30)
                )
                result = await self.sync_service.sync_orders(
                    tenant,
                    shop_id=shop,
                    trigger="manual",
                    mode="incremental",
                    updated_from=start,
                    updated_to=end,
                )
                results.append(
                    {
                        "shopId": str(shop),
                        "status": result.status,
                        "syncedAt": end
                        if result.status == "succeeded"
                        else cursor.last_success_at,
                    }
                )
            except (RuntimeError, ValueError, TikTokClientError, SQLAlchemyError):
                results.append(
                    {
                        "shopId": str(shop),
                        "status": "failed",
                        "syncedAt": cursor.last_success_at,
                    }
                )
            finally:
                await self.redis.eval(
                    "if redis.call('get',KEYS[1]) == ARGV[1] then return redis.call('del',KEYS[1]) end return 0",
                    1,
                    lock,
                    owner,
                )
        return results


def read_snapshot(value):
    snapshot = json.loads(value)
    if snapshot.get("ruleVersion") != 2:
        snapshot["deliveredAt"] = None
        snapshot["collectedAt"] = None
        snapshot["trackingStatus"] = "pending_recheck"
    return snapshot
