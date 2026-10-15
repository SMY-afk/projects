"""Bound production worker concurrency without changing local worker settings."""

from erp_api.workers.sample_settings import SampleWorkerSettings
from erp_api.workers.settings import WorkerSettings


class ProductionWorkerSettings(WorkerSettings):
    functions = WorkerSettings.functions
    cron_jobs = WorkerSettings.cron_jobs
    on_startup = WorkerSettings.on_startup
    on_shutdown = WorkerSettings.on_shutdown
    max_tries = WorkerSettings.max_tries
    redis_settings = WorkerSettings.redis_settings
    max_jobs = 2


class ProductionSampleWorkerSettings(SampleWorkerSettings):
    functions = SampleWorkerSettings.functions
    cron_jobs = SampleWorkerSettings.cron_jobs
    on_startup = SampleWorkerSettings.on_startup
    on_shutdown = SampleWorkerSettings.on_shutdown
    queue_name = SampleWorkerSettings.queue_name
    health_check_interval = SampleWorkerSettings.health_check_interval
    health_check_key = SampleWorkerSettings.health_check_key
    handle_signals = SampleWorkerSettings.handle_signals
    job_completion_wait = SampleWorkerSettings.job_completion_wait
    job_timeout = SampleWorkerSettings.job_timeout
    max_tries = SampleWorkerSettings.max_tries
    redis_settings = SampleWorkerSettings.redis_settings
    max_jobs = 2
