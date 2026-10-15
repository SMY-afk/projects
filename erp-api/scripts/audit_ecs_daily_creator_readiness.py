"""Read-only ECS probe for the five-shop daily creator evidence gate."""

import asyncio
from datetime import UTC, datetime

from arq.connections import RedisSettings, create_pool

from erp_api.core.config import get_settings
from erp_api.infrastructure.database import Database
from erp_api.services.affiliate_capture_health import AffiliateCaptureHealthRepository
from erp_api.services.affiliate_local_export_service import TARGET_SHOPS
from erp_api.workers.affiliate_live_schedule import _active_live_shops
from erp_api.workers.daily_valid_creator_jobs import _ready_snapshot


async def main() -> None:
    settings = get_settings()
    if settings.affiliate_export_tenant_id is None:
        print("DAILY_PREFLIGHT=BLOCKED REASON=tenant_not_configured")
        return
    database = Database(settings.database_url)
    redis = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    context = {"database": database, "redis": redis}
    try:
        shops = await _active_live_shops(database)
        target_names = {shop.source_name for shop in TARGET_SHOPS}
        selected = [
            shop
            for shop in shops
            if shop.tenant_id == settings.affiliate_export_tenant_id
            and shop.source_name in target_names
        ]
        print(f"TARGET_SHOPS={len(target_names)} FOUND_SHOPS={len(selected)}")
        health_repository = AffiliateCaptureHealthRepository(redis)
        now = datetime.now(UTC)
        for shop in sorted(selected, key=lambda item: item.source_name):
            health = await health_repository.get(shop.tenant_id, shop.shop_id)
            observed = [
                await health_repository.observed_evidence_for(
                    shop.tenant_id, shop.shop_id, resource, now=now
                )
                for resource in ("creators", "videos", "liveAccounts")
            ]
            print(
                f"SHOP={shop.source_name} STATE={health.state} "
                f"SESSION={health.session_available} "
                f"CREATORS={observed[0] is not None} "
                f"VIDEOS={observed[1] is not None} "
                f"LIVE={observed[2] is not None}"
            )
        try:
            snapshot = await _ready_snapshot(context, now)
        except (RuntimeError, ValueError) as error:
            print(f"DAILY_PREFLIGHT=BLOCKED REASON={type(error).__name__}")
        else:
            print(f"DAILY_PREFLIGHT={'READY' if snapshot is not None else 'BLOCKED'}")
        print(f"DAILY_QUEUE_JOBS={await redis.zcard('arq:daily-valid-creators')}")
    finally:
        await redis.aclose()
        await database.dispose()


if __name__ == "__main__":
    asyncio.run(main())
