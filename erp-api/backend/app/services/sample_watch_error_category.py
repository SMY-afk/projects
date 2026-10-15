from __future__ import annotations

import re

from erp_api.services.feishu_sample_errors import FeishuSampleError

_SAFE_CODE = re.compile(r"(?:\d{1,10}|http_\d{3}|transport_error)\Z")
_RETRYABLE_PAGE_CONTROL_ERRORS = {
    "sample_request_date_sort_unavailable",
    "sample_request_date_sort_unstable",
}
_RAW_RETRY_MARKERS = (
    "request pages are not contiguous",
    "request page marker is missing",
    "duplicate request id",
    "duplicate cursor",
    "terminal page",
    "pagination",
    "captured total",
    "expected total",
    "no review request-date response",
    "connection closed",
    "connection refused",
    "econnrefused",
    "websocket error",
    "browser has been closed",
    "target page, context or browser has been closed",
)
_CDP_REDISCOVERY_MARKERS = (
    "cdp connection closed",
    "connection refused",
    "econnrefused",
    "websocket error",
    "browser has been closed",
    "target page, context or browser has been closed",
)
_SOURCE_INCOMPLETE_MARKERS = (
    "pagination",
    "incomplete",
    "changed during reading",
    "captured total",
    "expected total",
    "terminal page",
    "duplicate cursor",
    "duplicate request id",
    "request page",
    "queue backlog",
)


def is_retryable_page_control_error(error: Exception) -> bool:
    return isinstance(error, RuntimeError) and str(error) in (
        _RETRYABLE_PAGE_CONTROL_ERRORS
    )


def is_retryable_raw_capture_error(error: Exception) -> bool:
    message = str(error).casefold()
    return (
        is_retryable_page_control_error(error)
        or isinstance(error, (TimeoutError, ConnectionError))
        or any(marker in message for marker in _RAW_RETRY_MARKERS)
    )


def requires_cdp_rediscovery(error: Exception) -> bool:
    message = str(error).casefold()
    return isinstance(error, ConnectionError) or any(
        marker in message for marker in _CDP_REDISCOVERY_MARKERS
    )


def classify_watch_error(error: Exception) -> tuple[str, str | None]:
    """Return only fixed operational categories and safe Feishu error codes."""
    if isinstance(error, FeishuSampleError):
        raw_code = error.error_code
        code = raw_code if _SAFE_CODE.fullmatch(raw_code) else None
        if code == "99991403":
            return "monthly_quota", code
        if code in {"transport_error", "99991400", "http_429"} or (
            code is not None and code.startswith("http_5")
        ):
            return "transient_transport", code
        message = str(error).lower()
        if any(marker in message for marker in _SOURCE_INCOMPLETE_MARKERS):
            return "source_incomplete", None
        return "feishu_business", code if code != "feishu_error" else None
    if isinstance(error, TimeoutError):
        return "timeout", None
    if isinstance(error, RuntimeError) and any(
        marker in str(error).lower() for marker in _SOURCE_INCOMPLETE_MARKERS
    ):
        return "source_incomplete", None
    return "unexpected", None
