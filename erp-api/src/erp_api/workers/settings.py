from __future__ import annotations

import importlib
from typing import ClassVar

from arq.connections import RedisSettings
from arq.cron import cron
from arq.worker import func

from erp_api.core.config import get_settings
from erp_api.core.logging import configure_logging
from erp_api.infrastructure.database import Database
from erp_api.workers.affiliate_creator_jobs import (
    enqueue_scheduled_affiliate_creator_syncs,
)
from erp_api.workers.affiliate_live_schedule import (
    enqueue_scheduled_affiliate_live_syncs,
)
from erp_api.workers.affiliate_official_jobs import (
    enqueue_scheduled_official_affiliate_syncs,
    sync_official_affiliate_job,
)
from erp_api.workers.affiliate_video_jobs import (
    enqueue_scheduled_affiliate_video_syncs,
)
from erp_api.workers.analytics_jobs import (
    enqueue_hourly_video_syncs,
    enqueue_scheduled_analytics_syncs,
    purge_analytics_raw_payloads_job,
    sync_analytics_job,
)
from erp_api.workers.bestseller_jobs import (
    enqueue_scheduled_bestseller_syncs,
    sync_bestseller_job,
)
from erp_api.workers.finance_jobs import (
    enqueue_scheduled_finance_syncs,
    sync_finance_job,
)
from erp_api.workers.logistics_tracking_jobs import (
    detect_logistics_exceptions_job,
    enqueue_due_logistics_tracking_polls,
    poll_logistics_tracking_job,
    sync_tiktok_logistics_job,
)
from erp_api.workers.order_jobs import (
    enqueue_scheduled_order_syncs,
    process_order_webhook_job,
    purge_order_pii_job,
    sync_order_job,
)
from erp_api.workers.platform_fulfillment_jobs import (
    enqueue_due_platform_fulfillments,
    process_platform_fulfillment_job,
)
from erp_api.workers.product_jobs import (
    enqueue_scheduled_product_syncs,
    sync_product_job,
)


async def startup(ctx):
    app_module = importlib.import_module("erp_api.main")
    settings = get_settings()
    configure_logging(settings.log_level)
    database = Database(settings.database_url)
    analytics_services = (
        app_module.build_analytics_services(
            settings, database, redis_client=ctx["redis"]
        )
        if "redis" in ctx
        else app_module.build_analytics_services(settings, database)
    )
    services = {
        **app_module.build_order_services(settings, database),
        **analytics_services,
        **app_module.build_product_services(settings, database),
    }
    tracking_builder = getattr(app_module, "build_logistics_tracking_services", None)
    if tracking_builder is not None:
        services.update(tracking_builder(settings, database))
    fulfillment_builder = getattr(
        app_module, "build_platform_fulfillment_services", None
    )
    if fulfillment_builder is not None:
        services.update(fulfillment_builder(settings, database))
    finance_builder = getattr(app_module, "build_finance_services", None)
    if finance_builder is not None:
        services.update(finance_builder(settings, database))
    from erp_api.services.token_cipher import TokenCipher
    from erp_api.services.webhook_service import WebhookService

    webhook_service = (
        WebhookService(
            database,
            settings.tiktok_webhook_signing_secret,
            TokenCipher(settings.order_pii_encryption_key.get_secret_value()),
        )
        if settings.tiktok_webhook_signing_secret and settings.order_pii_encryption_key
        else None
    )
    ctx.update(
        database=database,
        webhook_service=webhook_service,
        analytics_sync_max_tries=settings.tiktok_analytics_job_max_tries,
        finance_sync_max_tries=getattr(settings, "tiktok_finance_job_max_tries", 5),
        **services,
    )
    await enqueue_scheduled_bestseller_syncs(ctx)


async def shutdown(ctx):
    await ctx["database"].dispose()


def _analytics_daily_cron():
    settings = get_settings()
    return cron(
        enqueue_scheduled_analytics_syncs,
        hour=settings.tiktok_analytics_sync_hour_utc,
        minute=settings.tiktok_analytics_sync_minute_utc,
    )


def _bestseller_daily_cron():
    settings = get_settings()
    return cron(
        enqueue_scheduled_bestseller_syncs,
        hour=settings.tiktok_bestseller_sync_hour_utc,
        minute=settings.tiktok_bestseller_sync_minute_utc,
    )


def _finance_incremental_cron():
    settings = get_settings()
    interval = settings.tiktok_finance_sync_interval_minutes
    return cron(
        enqueue_scheduled_finance_syncs,
        minute=set(range(0, 60, interval)),
    )


class WorkerSettings:
    functions: ClassVar[list] = [
        sync_order_job,
        process_order_webhook_job,
        enqueue_scheduled_order_syncs,
        purge_order_pii_job,
        sync_analytics_job,
        func(sync_official_affiliate_job, max_tries=24),
        enqueue_scheduled_official_affiliate_syncs,
        enqueue_hourly_video_syncs,
        enqueue_scheduled_analytics_syncs,
        enqueue_scheduled_affiliate_creator_syncs,
        enqueue_scheduled_affiliate_video_syncs,
        enqueue_scheduled_affiliate_live_syncs,
        purge_analytics_raw_payloads_job,
        sync_bestseller_job,
        enqueue_scheduled_bestseller_syncs,
        func(sync_product_job, timeout=900),
        enqueue_scheduled_product_syncs,
        func(sync_finance_job, timeout=840),
        enqueue_scheduled_finance_syncs,
        process_platform_fulfillment_job,
        enqueue_due_platform_fulfillments,
        poll_logistics_tracking_job,
        enqueue_due_logistics_tracking_polls,
        detect_logistics_exceptions_job,
        sync_tiktok_logistics_job,
    ]
    cron_jobs: ClassVar[list] = [
        cron(enqueue_scheduled_order_syncs, minute={0, 10, 20, 30, 40, 50}),
        cron(purge_order_pii_job, hour=2, minute=0),
        cron(
            enqueue_hourly_video_syncs,
            minute=get_settings().tiktok_analytics_sync_minute_utc,
        ),
        _analytics_daily_cron(),
        cron(
            enqueue_scheduled_official_affiliate_syncs,
            hour=get_settings().tiktok_analytics_sync_hour_utc,
            minute=get_settings().tiktok_analytics_sync_minute_utc,
        ),
        _bestseller_daily_cron(),
        _finance_incremental_cron(),
        cron(enqueue_scheduled_affiliate_creator_syncs, minute=set(range(0, 60, 10))),
        cron(enqueue_scheduled_affiliate_video_syncs, minute=set(range(0, 60, 10))),
        cron(enqueue_scheduled_affiliate_live_syncs, minute=set(range(0, 60, 10))),
        cron(
            enqueue_scheduled_product_syncs,
            minute=get_settings().tiktok_product_sync_minute_utc,
        ),
        cron(purge_analytics_raw_payloads_job, hour=3, minute=0),
        cron(enqueue_due_platform_fulfillments, minute=set(range(60))),
        cron(enqueue_due_logistics_tracking_polls, minute={5, 15, 25, 35, 45, 55}),
        cron(
            sync_tiktok_logistics_job,
            minute={1, 11, 21, 31, 41, 51},
            job_id="cron:sync-tiktok-logistics",
            timeout=get_settings().tiktok_logistics_sync_job_timeout_seconds,
        ),
        cron(detect_logistics_exceptions_job, minute={3, 13, 23, 33, 43, 53}),
    ]
    on_startup = startup
    on_shutdown = shutdown
    max_tries = max(
        get_settings().tiktok_analytics_job_max_tries,
        get_settings().tiktok_finance_job_max_tries,
        get_settings().platform_fulfillment_job_max_tries,
    )
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
