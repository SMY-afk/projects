from __future__ import annotations

import asyncio
import sys
from types import ModuleType, SimpleNamespace

from erp_api.services.sample_shop_sync_lock import SampleShopSyncLock
from erp_api.workers import (
    sample_application_jobs,
    sample_feishu_maintenance_jobs,
    sample_settings,
)
from erp_api.workers.settings import WorkerSettings


def test_sample_worker_has_isolated_queue_and_startup(monkeypatch) -> None:
    configured_levels: list[str] = []
    validations: list[str] = []

    class FeishuClient:
        async def validate_required_fields(self):
            validations.append("validated")

    class Mirror:
        async def validate(self):
            raise AssertionError("Unused mirror must not be read at startup")

    app_module = ModuleType("erp_api.main")
    app_module.build_sample_application_services = lambda settings, database, **kwargs: {
        "sample_shop_pipeline_service": "sample-pipeline",
        "feishu_sample_client_router": FeishuClient(),
        "sample_ai_invitation_mirror_service": Mirror(),
    }
    settings = SimpleNamespace(
        log_level="INFO",
        database_url="postgresql+asyncpg://example.invalid/erp",
        tiktok_sample_shop_lock_retry_seconds=30,
        feishu_ai_invitation_sheet_token="",
        feishu_ai_invitation_sheet_id="",
    )
    database = SimpleNamespace(engine=object())
    monkeypatch.setitem(sys.modules, "erp_api.main", app_module)
    monkeypatch.setattr(sample_settings, "get_settings", lambda: settings)
    monkeypatch.setattr(sample_settings, "Database", lambda _url: database)
    monkeypatch.setattr(sample_settings, "configure_logging", configured_levels.append)

    context = {}
    asyncio.run(sample_settings.startup(context))

    assert sample_settings.SampleWorkerSettings.queue_name == "arq:sample"
    assert sample_settings.SampleWorkerSettings.health_check_interval == 30
    assert (
        sample_settings.SampleWorkerSettings.health_check_key
        == "arq:sample:health-check"
    )
    assert configured_levels == ["INFO"]
    assert validations == ["validated"]
    assert context["sample_shop_pipeline_service"] == "sample-pipeline"
    assert isinstance(context["sample_shop_sync_lock"], SampleShopSyncLock)
    assert context["sample_shop_lock_retry_seconds"] == 30
    assert sample_application_jobs.sync_sample_applications_job not in (
        WorkerSettings.functions
    )
    assert "enqueue_active_sample_application_polls" not in repr(
        WorkerSettings.cron_jobs
    )


def test_fast_and_reconciliation_jobs_have_separate_timeouts() -> None:
    functions = {
        function.name: function
        for function in sample_settings.SampleWorkerSettings.functions
        if hasattr(function, "name")
    }

    assert functions["sync_sample_applications_job"].timeout_s == 900
    assert functions["reconcile_sample_applications_job"].timeout_s == 3600
    assert functions["process_remote_sample_batch_job"].timeout_s == 3600
    assert functions["send_sample_notification_job"].max_tries == 60
    assert sample_settings.SampleWorkerSettings.handle_signals is True
    assert sample_settings.SampleWorkerSettings.job_completion_wait == 120


def test_bd_invitation_collection_background_cleanup_is_minutely() -> None:
    scheduled = next(
        job
        for job in sample_settings.SampleWorkerSettings.cron_jobs
        if job.coroutine
        is sample_feishu_maintenance_jobs.cleanup_bd_invitation_protection_job
    )

    assert scheduled.minute == set(range(60))


def test_ai_invitation_mirror_is_not_loaded_as_automatic_job() -> None:
    assert all(
        job.coroutine
        is not sample_feishu_maintenance_jobs.sync_ai_invitation_mirror_job
        for job in sample_settings.SampleWorkerSettings.cron_jobs
    )
    assert all(
        getattr(function, "name", None) != "sync_ai_invitation_mirror_job"
        and function is not sample_feishu_maintenance_jobs.sync_ai_invitation_mirror_job
        for function in sample_settings.SampleWorkerSettings.functions
    )


def test_countdown_refresh_runs_every_five_minutes():
    scheduled = next(
        job
        for job in sample_settings.SampleWorkerSettings.cron_jobs
        if job.coroutine.__name__ == "refresh_sample_time_left_job"
    )
    assert scheduled.minute == set(range(1, 60, 5))
