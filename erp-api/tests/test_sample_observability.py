from types import SimpleNamespace

from erp_api.services.sample_observability import (
    log_sample_sync_failure,
    log_sample_sync_success,
    safe_sample_error_code,
)


class RecordingLogger:
    def __init__(self) -> None:
        self.calls = []

    def info(self, message, *, extra):
        self.calls.append(("info", message, extra))

    def warning(self, message, *, extra):
        self.calls.append(("warning", message, extra))


def test_success_log_contains_only_safe_dimensions_counts_and_duration() -> None:
    logger = RecordingLogger()
    result = SimpleNamespace(
        source_results=(
            SimpleNamespace(record_count=3),
            SimpleNamespace(record_count=5),
        ),
        feishu_result=SimpleNamespace(created_count=2, updated_count=4),
        notification_results=("sent",),
    )

    log_sample_sync_success(
        logger,
        tenant_id="tenant-1",
        shop_id="shop-1",
        request_id="job-1",
        duration_ms=12.345,
        result=result,
    )

    assert logger.calls == [
        (
            "info",
            "sample_sync_succeeded",
            {
                "event": "sample_sync_succeeded",
                "tenant_id": "tenant-1",
                "shop_id": "shop-1",
                "request_id": "job-1",
                "records_read": 8,
                "records_created": 2,
                "records_updated": 4,
                "notification_count": 1,
                "duration_ms": 12.35,
            },
        )
    ]


def test_failure_log_never_uses_exception_message_or_unsafe_error_code() -> None:
    class UnsafeFailure(RuntimeError):
        error_code = "token=secret-value"

    logger = RecordingLogger()
    error = UnsafeFailure("Cookie=secret; sign=secret")

    log_sample_sync_failure(
        logger,
        tenant_id="tenant-1",
        shop_id="shop-1",
        request_id="job-1",
        duration_ms=8.1,
        error=error,
    )

    _level, message, extra = logger.calls[0]
    assert message == "sample_sync_failed"
    assert extra == {
        "event": "sample_sync_failed",
        "tenant_id": "tenant-1",
        "shop_id": "shop-1",
        "request_id": "job-1",
        "duration_ms": 8.1,
        "error_code": "UnsafeFailure",
    }
    assert "secret" not in repr(logger.calls)


def test_safe_platform_error_code_is_preserved() -> None:
    error = RuntimeError("must not be logged")
    error.code = "rate_limited"  # type: ignore[attr-defined]

    assert safe_sample_error_code(error) == "rate_limited"
