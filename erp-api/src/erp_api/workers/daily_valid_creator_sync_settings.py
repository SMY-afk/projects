"""Dedicated Feishu daily-sync worker; browser exports run on the local PC."""

from typing import ClassVar

from arq.connections import RedisSettings
from arq.cron import cron
from arq.worker import func

from erp_api.core.config import get_settings
from erp_api.infrastructure.database import Database
from erp_api.workers.daily_valid_creator_cleanup_jobs import (
    cleanup_daily_valid_creators_job,
)
from erp_api.workers.daily_valid_creator_jobs import (
    QUEUE_NAME,
    enqueue_due_valid_creator_syncs,
    sync_daily_valid_creator_job,
)


async def startup(ctx) -> None:
    ctx["database"] = Database(get_settings().database_url)


async def shutdown(ctx) -> None:
    await ctx["database"].dispose()


class DailyValidCreatorSyncWorkerSettings:
    functions: ClassVar[list] = [
        enqueue_due_valid_creator_syncs,
        func(sync_daily_valid_creator_job, max_tries=1, timeout=3600),
        func(cleanup_daily_valid_creators_job, max_tries=1, timeout=3600),
    ]
    cron_jobs: ClassVar[list] = [
        cron(enqueue_due_valid_creator_syncs, minute=set(range(60))),
    ]
    on_startup = startup
    on_shutdown = shutdown
    queue_name = QUEUE_NAME
    max_jobs = 1
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
