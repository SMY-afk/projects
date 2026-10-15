"""Same serial daily worker plus one explicitly authorized update function."""

from arq.worker import func

from erp_api.workers.daily_valid_creator_manual_jobs import update_current_daily_creators_job
from erp_api.workers.daily_valid_creator_sync_settings import DailyValidCreatorSyncWorkerSettings as Base


class CurrentDailyCreatorWorkerSettings:
    functions = [*Base.functions, func(update_current_daily_creators_job, max_tries=1, timeout=3600)]
    cron_jobs = Base.cron_jobs
    on_startup = Base.on_startup
    on_shutdown = Base.on_shutdown
    queue_name = Base.queue_name
    max_jobs = Base.max_jobs
    redis_settings = Base.redis_settings
    job_completion_wait = 120
