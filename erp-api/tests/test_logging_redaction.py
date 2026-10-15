import json
import logging
import sys

import pytest

from backend.app.services.capture_logging import capture_log, safe_error
from erp_api.core.logging import JsonFormatter, SensitiveDataFilter


@pytest.mark.parametrize(
    "message",
    [
        "access_token=synthetic-access-value",
        "refresh-token: synthetic-refresh-value",
        '{"app_secret": "synthetic-app-value"}',
        "client_secret='synthetic-client-value'",
        "sign=synthetic-sign-value",
        "request_sign=synthetic-prefixed-sign-value",
        'signature: "synthetic-signature-value"',
        "shop_cipher=synthetic-cipher-value",
        "Authorization: Bearer synthetic-bearer-value",
        "X-Tts-Access-Token=synthetic-header-value",
        "https://example.invalid/path?shop_cipher=synthetic-query-value&limit=10",
    ],
)
def test_json_formatter_redacts_sensitive_values(message: str) -> None:
    record = logging.LogRecord(
        name="erp_api.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=(),
        exc_info=None,
    )

    payload = json.loads(JsonFormatter().format(record))

    assert "synthetic-" not in payload["message"]
    assert "[REDACTED]" in payload["message"]


def test_json_formatter_redacts_allowlisted_string_extra() -> None:
    record = logging.LogRecord(
        name="erp_api.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="request_completed",
        args=(),
        exc_info=None,
    )
    record.path = "/callback?sign=synthetic-path-value"

    payload = json.loads(JsonFormatter().format(record))

    assert payload["path"] == "/callback?sign=[REDACTED]"


def test_json_formatter_preserves_non_sensitive_signature_message() -> None:
    record = logging.LogRecord(
        name="erp_api.test",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg="Webhook signature is invalid.",
        args=(),
        exc_info=None,
    )

    payload = json.loads(JsonFormatter().format(record))

    assert payload["message"] == "Webhook signature is invalid."


def test_capture_log_redacts_nested_sensitive_values(
    capsys: pytest.CaptureFixture[str],
) -> None:
    capture_log(
        "synthetic_event",
        request={
            "url": "/resource?sign=synthetic-capture-value",
            "headers": {"Authorization": "Bearer synthetic-auth-value"},
        },
    )

    payload = json.loads(capsys.readouterr().out)

    assert "synthetic-" not in json.dumps(payload)
    assert payload["request"]["url"] == "/resource?sign=[REDACTED]"
    assert payload["request"]["headers"]["Authorization"] == "[REDACTED]"


def test_safe_error_redacts_sensitive_query_value() -> None:
    error = RuntimeError(
        "Request failed: /resource?shop_cipher=synthetic-error-value&limit=10"
    )

    result = safe_error(error)

    assert result == "Request failed: /resource?shop_cipher=[REDACTED]&limit=10"


def test_sensitive_data_filter_redacts_exception_text() -> None:
    try:
        raise RuntimeError("Request failed: /resource?sign=synthetic-trace-value")
    except RuntimeError:
        record = logging.LogRecord(
            name="external.worker",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="job_failed",
            args=(),
            exc_info=sys.exc_info(),
        )

    assert SensitiveDataFilter().filter(record)
    output = logging.Formatter().format(record)

    assert "synthetic-" not in output
    assert "sign=[REDACTED]" in output
