"""Keep the production finance job within its own bounded window."""

from erp_api.workers.settings import WorkerSettings


def test_finance_job_has_a_dedicated_timeout() -> None:
    finance = next(
        job for job in WorkerSettings.functions
        if getattr(job, "name", getattr(job, "__name__", None)) == "sync_finance_job"
    )
    assert finance.timeout_s == 840
