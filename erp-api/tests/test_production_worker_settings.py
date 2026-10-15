from arq.worker import get_kwargs

from erp_api.workers.production_settings import (
    ProductionSampleWorkerSettings,
    ProductionWorkerSettings,
)


def test_production_workers_keep_registered_jobs_and_limits() -> None:
    for settings in (ProductionWorkerSettings, ProductionSampleWorkerSettings):
        kwargs = get_kwargs(settings)
        assert kwargs["functions"]
        assert kwargs["cron_jobs"]
        assert kwargs["on_startup"]
        assert kwargs["on_shutdown"]
        assert kwargs["redis_settings"]
        assert kwargs["max_jobs"] == 2
