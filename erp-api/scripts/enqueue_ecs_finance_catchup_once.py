"""Queue one guarded ECS finance catch-up chunk for the exact high-volume shop."""

import argparse
import asyncio
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit
from uuid import UUID

from arq.connections import RedisSettings, create_pool
from sqlalchemy import select

from erp_api.core.config import get_settings
from erp_api.infrastructure.database import Database
from erp_api.models.finance_sync import FinanceSyncCursor, FinanceSyncRun


TENANT_ID = UUID("6d0032eb-6a58-5a93-a819-d55c2a1c2e26")
SHOP_ID = UUID("6fdc5cdc-90da-5524-82f7-9b11746c5e10")
RDS_HOST = "pgm-wz9bb45790nb73dc.pg.rds.aliyuncs.com"


async def main(apply: bool) -> None:
    settings = get_settings()
    if (
        urlsplit(settings.database_url).hostname != RDS_HOST
        or urlsplit(settings.redis_url).hostname != "127.0.0.1"
    ):
        raise SystemExit("STOP_CATCHUP_RUNTIME_TARGET")
    database = Database(settings.database_url)
    try:
        async with database.system_session_factory() as session:
            latest = await session.scalar(
                select(FinanceSyncRun)
                .where(
                    FinanceSyncRun.tenant_id == TENANT_ID,
                    FinanceSyncRun.shop_id == SHOP_ID,
                )
                .order_by(FinanceSyncRun.started_at.desc())
                .limit(1)
            )
            cursor = await session.scalar(
                select(FinanceSyncCursor).where(
                    FinanceSyncCursor.tenant_id == TENANT_ID,
                    FinanceSyncCursor.shop_id == SHOP_ID,
                    FinanceSyncCursor.entity_type == "finance",
                )
            )
        now = datetime.now(UTC)
        if (
            latest is None
            or latest.status != "succeeded"
            or cursor is None
            or cursor.last_successful_at != latest.window_to
            or now - cursor.last_successful_at < timedelta(days=1)
        ):
            raise SystemExit("STOP_CATCHUP_PREVIOUS_RUN_OR_CURSOR")
        minutes_to_cron = 15 - now.minute % 15
        if minutes_to_cron <= 3 or (now - latest.finished_at).total_seconds() < 10:
            raise SystemExit("STOP_CATCHUP_TOO_CLOSE_TO_CRON_OR_PREVIOUS_RUN")
        job_id = f"finance-catchup-301:{cursor.last_successful_at:%Y%m%dT%H%M%S}"
        print(
            f"CATCHUP_PREVIEW SHOP=Akeleo_Toys LAST_CURSOR={cursor.last_successful_at.isoformat()} "
            f"LAG_DAYS={(now-cursor.last_successful_at).days} "
            f"MINUTES_TO_CRON={minutes_to_cron} JOB_ID={job_id}"
        )
        if not apply:
            return
        redis = await create_pool(RedisSettings.from_dsn(settings.redis_url))
        try:
            job = await redis.enqueue_job(
                "sync_finance_job",
                str(TENANT_ID),
                str(SHOP_ID),
                "incremental",
                _job_id=job_id,
            )
            if job is None:
                raise SystemExit("STOP_CATCHUP_JOB_ALREADY_EXISTS")
            print("CATCHUP_ENQUEUED")
        finally:
            await redis.aclose()
    finally:
        await database.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args.apply))
