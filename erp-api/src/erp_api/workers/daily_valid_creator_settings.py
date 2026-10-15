"""Isolated one-at-a-time queue for verified daily Feishu creator updates."""

from typing import ClassVar

from arq.connections import RedisSettings
from arq.cron import cron
from arq.worker import func

from erp_api.core.config import get_settings
from erp_api.infrastructure.database import Database
from erp_api.workers.affiliate_creator_jobs import (
    enqueue_scheduled_affiliate_creator_syncs,
)
from erp_api.workers.affiliate_live_schedule import (
    enqueue_scheduled_affiliate_live_syncs,
)
from erp_api.workers.affiliate_video_jobs import (
    enqueue_scheduled_affiliate_video_syncs,
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


class DailyValidCreatorWorkerSettings:
    functions: ClassVar[list] = [
        enqueue_scheduled_affiliate_creator_syncs,
        enqueue_scheduled_affiliate_video_syncs,
        enqueue_scheduled_affiliate_live_syncs,
        enqueue_due_valid_creator_syncs,
        func(sync_daily_valid_creator_job, max_tries=1, timeout=3600),
    ]
    cron_jobs: ClassVar[list] = [
        cron(enqueue_due_valid_creator_syncs, minute=set(range(60))),
        cron(
            enqueue_scheduled_affiliate_creator_syncs,
            minute=set(range(0, 60, 10)),
            job_id="cron:daily-valid-creators:capture-creators",
        ),
        cron(
            enqueue_scheduled_affiliate_video_syncs,
            minute=set(range(0, 60, 10)),
            job_id="cron:daily-valid-creators:capture-videos",
        ),
        cron(
            enqueue_scheduled_affiliate_live_syncs,
            minute=set(range(0, 60, 10)),
            job_id="cron:daily-valid-creators:capture-live",
        ),
    ]
    on_startup = startup
    on_shutdown = shutdown
    queue_name = QUEUE_NAME
    max_jobs = 1
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
