from erp_api.workers.daily_valid_creator_sync_settings import (
    DailyValidCreatorSyncWorkerSettings,
)


def test_daily_sync_worker_does_not_schedule_browser_exports() -> None:
    settings = DailyValidCreatorSyncWorkerSettings
    assert settings.queue_name == "arq:daily-valid-creators"
    assert settings.max_jobs == 1
    assert len(settings.cron_jobs) == 1
    assert settings.cron_jobs[0].coroutine.__name__ == "enqueue_due_valid_creator_syncs"
    assert "enqueue_scheduled_affiliate_creator_syncs" not in str(settings.functions)
    assert "enqueue_scheduled_affiliate_video_syncs" not in str(settings.functions)
