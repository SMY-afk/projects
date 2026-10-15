from backend.app.services.sample_watch_error_category import (
    classify_watch_error,
    is_retryable_page_control_error,
)


def test_only_request_date_sort_unavailable_is_retryable() -> None:
    assert is_retryable_page_control_error(
        RuntimeError("sample_request_date_sort_unavailable")
    )
    assert not is_retryable_page_control_error(
        RuntimeError("sample_review_status_unavailable")
    )
    assert not is_retryable_page_control_error(TimeoutError("capture_timeout"))
from erp_api.services.feishu_sample_errors import FeishuSampleError


def test_classifies_monthly_quota_without_message() -> None:
    error = FeishuSampleError("remote message", error_code="99991403")
    assert classify_watch_error(error) == ("monthly_quota", "99991403")


def test_classifies_transient_transport_and_incomplete_pagination() -> None:
    transport = FeishuSampleError("request failed", error_code="transport_error")
    pagination = FeishuSampleError("record pagination is incomplete")
    assert classify_watch_error(transport) == ("transient_transport", "transport_error")
    assert classify_watch_error(pagination) == ("source_incomplete", None)


def test_discards_untrusted_error_code() -> None:
    error = FeishuSampleError("remote message", error_code="secret=do-not-log")
    assert classify_watch_error(error) == ("feishu_business", None)


def test_raw_pagination_total_mismatch_is_source_incomplete() -> None:
    error = RuntimeError(
        "RAW sample captured total does not match expected total"
    )

    assert classify_watch_error(error) == ("source_incomplete", None)
