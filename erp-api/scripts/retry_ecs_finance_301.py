"""Enqueue one audited retry for the 301 shop finance sync."""

import argparse
import asyncio
from pathlib import Path

from arq.connections import RedisSettings, create_pool

from erp_api.core.config import Settings


TENANT_ID = "6d0032eb-6a58-5a93-a819-d55c2a1c2e26"
SHOP_ID = "6fdc5cdc-90da-5524-82f7-9b11746c5e10"
JOB_ID = "finance-retry-301-20261009-0551"


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    settings = Settings(_env_file=Path("/etc/erp/erp-api.env"))
    print(f"FINANCE_RETRY_PREVIEW SHOP_ID={SHOP_ID} JOB_ID={JOB_ID}")
    if not args.apply:
        return
    redis = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    try:
        result = await redis.enqueue_job(
            "sync_finance_job", TENANT_ID, SHOP_ID, "incremental", _job_id=JOB_ID
        )
        if result is None:
            raise SystemExit("STOP_FINANCE_RETRY_ALREADY_EXISTS")
        print("FINANCE_RETRY_ENQUEUED")
    finally:
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(main())
