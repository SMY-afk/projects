from __future__ import annotations

import importlib
from typing import ClassVar

from arq.connections import RedisSettings
from arq.cron import cron
from arq.worker import func

from erp_api.core.config import get_settings
from erp_api.core.logging import configure_logging
from erp_api.infrastructure.database import Database
from erp_api.services.sample_assignment_summary_service import (
    ASSIGNMENT_SUMMARY_REVISION_KEY,
)
from erp_api.services.sample_bd_invitation_ai_priority import AiInvitationSnapshotStore
from erp_api.services.sample_shop_sync_lock import SampleShopSyncLock
from erp_api.workers.remote_sample_jobs import process_remote_sample_batch_job
from erp_api.workers.sample_application_jobs import (
    enqueue_active_sample_application_polls,
    enqueue_due_sample_notifications,
    enqueue_feishu_sample_reverse_poll,
    enqueue_feishu_sample_reverse_poll_audit,
    enqueue_sample_application_reconciliation,
    enqueue_sample_source_recoveries,
    enqueue_terminal_sample_application_polls,
    poll_feishu_sample_business_fields_job,
    reconcile_failed_sample_notifications,
    reconcile_sample_applications_job,
    recover_sample_application_source_job,
    send_sample_notification_job,
    sync_sample_applications_job,
)
from erp_api.workers.sample_feishu_maintenance_jobs import (
    cleanup_bd_invitation_protection_job,
)
from erp_api.workers.sample_queue import (
    SAMPLE_QUEUE_NAME,
    SAMPLE_WORKER_HEALTH_INTERVAL_SECONDS,
    SAMPLE_WORKER_HEALTH_KEY,
)
from erp_api.workers.sample_time_left_jobs import refresh_sample_time_left_job


async def startup(ctx):
    app_module = importlib.import_module("erp_api.main")
    settings = get_settings()
    configure_logging(settings.log_level)
    database = Database(settings.database_url)
    ai_snapshot_store = (
        AiInvitationSnapshotStore(
            ctx["redis"],
            spreadsheet_token=settings.feishu_ai_invitation_sheet_token,
            sheet_id=settings.feishu_ai_invitation_sheet_id,
        )
        if settings.feishu_ai_invitation_sheet_token
        and settings.feishu_ai_invitation_sheet_id
        else None
    )

    async def notify_assignment_change():
        await ctx["redis"].incr(ASSIGNMENT_SUMMARY_REVISION_KEY)

    services = app_module.build_sample_application_services(
        settings,
        database,
        ai_snapshot_store=ai_snapshot_store,
        assignment_change_notifier=notify_assignment_change,
    )
    if services.get("sample_shop_pipeline_service") is None:
        raise RuntimeError(
            "Sample worker requires configured TikTok and Feishu sync services."
        )
    feishu_clients = services.get("feishu_sample_client_router")
    if feishu_clients is not None:
        await feishu_clients.validate_required_fields()
    protection = services.get("sample_bd_invitation_protection_service")
    if protection is not None:
        await protection.validate()
    ctx.update(
        database=database,
        sample_shop_sync_lock=SampleShopSyncLock(database),
        sample_shop_lock_retry_seconds=settings.tiktok_sample_shop_lock_retry_seconds,
        **services,
    )


async def shutdown(ctx):
    await ctx["database"].dispose()


class SampleWorkerSettings:
    functions: ClassVar[list] = [
        func(
            sync_sample_applications_job,
            max_tries=get_settings().tiktok_sample_sync_job_max_tries,
            timeout=get_settings().tiktok_sample_fast_job_timeout_seconds,
        ),
        func(
            reconcile_sample_applications_job,
            max_tries=get_settings().tiktok_sample_sync_job_max_tries,
            timeout=get_settings().tiktok_sample_full_job_timeout_seconds,
        ),
        recover_sample_application_source_job,
        func(
            process_remote_sample_batch_job,
            max_tries=get_settings().tiktok_sample_sync_job_max_tries,
            timeout=get_settings().tiktok_sample_full_job_timeout_seconds,
        ),
        poll_feishu_sample_business_fields_job,
        func(
            send_sample_notification_job,
            max_tries=60,
            timeout=get_settings().tiktok_sample_fast_job_timeout_seconds,
        ),
        enqueue_active_sample_application_polls,
        enqueue_terminal_sample_application_polls,
        enqueue_sample_application_reconciliation,
        enqueue_sample_source_recoveries,
        enqueue_feishu_sample_reverse_poll,
        enqueue_feishu_sample_reverse_poll_audit,
        enqueue_due_sample_notifications,
        reconcile_failed_sample_notifications,
        cleanup_bd_invitation_protection_job,
        func(refresh_sample_time_left_job, timeout=600),
    ]
    cron_jobs: ClassVar[list] = [
        cron(refresh_sample_time_left_job, minute=set(range(1, 60, 5)), timeout=600),
        cron(enqueue_active_sample_application_polls, minute=set(range(0, 60, 5))),
        cron(
            enqueue_feishu_sample_reverse_poll,
            minute=set(
                range(0, 60, get_settings().feishu_sample_reverse_poll_interval_minutes)
            ),
        ),
        cron(enqueue_feishu_sample_reverse_poll_audit, hour=18, minute=30),
        # Keep new BD invitation remarks and AI snapshots current each minute.
        cron(cleanup_bd_invitation_protection_job, minute=set(range(60))),
        cron(enqueue_sample_source_recoveries, minute=set(range(2, 60, 5))),
        cron(enqueue_due_sample_notifications, minute=set(range(60))),
        cron(reconcile_failed_sample_notifications, minute=15),
        cron(enqueue_terminal_sample_application_polls, minute=7),
        cron(
            enqueue_sample_application_reconciliation,
            hour=get_settings().tiktok_sample_reconciliation_hour_utc,
            minute=get_settings().tiktok_sample_reconciliation_minute_utc,
        ),
    ]
    on_startup = startup
    on_shutdown = shutdown
    queue_name = SAMPLE_QUEUE_NAME
    health_check_interval = SAMPLE_WORKER_HEALTH_INTERVAL_SECONDS
    health_check_key = SAMPLE_WORKER_HEALTH_KEY
    handle_signals = True
    job_completion_wait = get_settings().tiktok_sample_shutdown_grace_seconds
    job_timeout = get_settings().tiktok_sample_fast_job_timeout_seconds
    max_tries = get_settings().tiktok_sample_sync_job_max_tries
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
