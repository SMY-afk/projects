"""Requeue one failed 301-app bestseller scope without replacing old jobs."""

import argparse
import asyncio
from pathlib import Path

from arq.connections import RedisSettings, create_pool

from erp_api.core.config import Settings


TENANT_ID = "6d0032eb-6a58-5a93-a819-d55c2a1c2e26"
SHOP_ID = "6fdc5cdc-90da-5524-82f7-9b11746c5e10"
REFERENCE_DATE = "2026-10-07"


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--entity", choices=("product", "creator", "video", "live"))
    parser.add_argument("--slot", choices=("1D", "7D", "30D"))
    parser.add_argument("--batch-rest", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    settings = Settings(_env_file=Path("/etc/erp/erp-api.env"))
    if not (settings.tiktok_301_app_key and settings.tiktok_301_app_secret and settings.tiktok_301_service_id):
        raise SystemExit("STOP_301_APP_CONFIG_MISSING")
    if args.batch_rest:
        if args.entity or args.slot:
            raise SystemExit("STOP_SCOPE_CONFLICT")
        scopes = [
            (entity, slot)
            for entity in ("product", "creator", "video", "live")
            for slot in ("1D", "7D", "30D")
            if (entity, slot) != ("product", "1D")
        ]
    elif args.entity and args.slot:
        scopes = [(args.entity, args.slot)]
    else:
        raise SystemExit("STOP_SCOPE_MISSING")
    if not args.apply:
        print(f"RETRY_PREVIEW COUNT={len(scopes)} SHOP_ID={SHOP_ID} DATE={REFERENCE_DATE}")
        return
    redis = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    try:
        for entity, slot in scopes:
            job_id = f"bestseller-retry-301-20261009:{entity}:{slot}"
            result = await redis.enqueue_job(
                "sync_bestseller_job",
                TENANT_ID,
                SHOP_ID,
                entity,
                REFERENCE_DATE,
                slot,
                "USD",
                "ALL" if entity == "creator" else None,
                _job_id=job_id,
            )
            if result is None:
                raise SystemExit(f"STOP_RETRY_JOB_ALREADY_EXISTS={job_id}")
            print(f"RETRY_ENQUEUED JOB_ID={job_id}", flush=True)
    finally:
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(main())
