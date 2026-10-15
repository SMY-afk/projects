from __future__ import annotations

from backend.app.services import tiktok_affiliate_analytics_run_state as run_state
from backend.app.services.tiktok_affiliate_analytics_page_control import capture_log


def log_terminal(
    guard: run_state.AffiliateAnalyticsRunGuard,
    resource: str,
    event: str,
) -> None:
    snapshot = guard.snapshot(resource)
    capture_log(
        event,
        pages_fetched=snapshot["pages_fetched"],
        records_received=snapshot["records_received"],
        records_unique=snapshot["records_unique"],
        duplicates=snapshot["duplicates"],
        expected_total=snapshot["expected_total"],
    )


def persistence_failure_event(error: Exception) -> str:
    suffix = {
        "TimeoutError": "timeout",
        "ValueError": "value_error",
        "TypeError": "type_error",
        "RuntimeError": "runtime_error",
    }.get(type(error).__name__, "unexpected")
    return f"affiliate_analytics_page_persist_failed_{suffix}"
