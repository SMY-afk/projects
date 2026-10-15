"""Keep the existing default queue and cron, but drain jobs before shutdown."""

from erp_api.workers.settings import WorkerSettings


class OrderRetryWorkerSettings:
    # ARQ reads __dict__, not inherited attributes; forward its exact config.
    functions = WorkerSettings.functions
    cron_jobs = WorkerSettings.cron_jobs
    on_startup = WorkerSettings.on_startup
    on_shutdown = WorkerSettings.on_shutdown
    max_tries = WorkerSettings.max_tries
    redis_settings = WorkerSettings.redis_settings
    job_completion_wait = 120
