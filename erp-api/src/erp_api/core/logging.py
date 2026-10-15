import json
import logging
import re
import sys
from contextvars import ContextVar
from datetime import UTC, datetime

request_id_context: ContextVar[str | None] = ContextVar("request_id", default=None)

_REDACTED = "[REDACTED]"
_SENSITIVE_KEY = (
    r"(?:access[_-]?token|refresh[_-]?token|tenant[_-]?access[_-]?token|"
    r"app[_-]?secret|client[_-]?secret|shop[_-]?cipher|authorization|"
    r"x[_-]?tts[_-]?access[_-]?token|x[_-]?lark[_-]?signature|sign(?:ature)?)"
)
_SENSITIVE_KEY_NAME = re.compile(rf"(?i)^{_SENSITIVE_KEY}$")
_QUOTED_SENSITIVE_VALUE = re.compile(
    rf"(?i)(?P<prefix>(?<![A-Za-z0-9-])[\"']?{_SENSITIVE_KEY}[\"']?\s*[:=]\s*)"
    r"(?P<quote>[\"'])(?P<value>[^\r\n]*?)(?P=quote)"
)
_UNQUOTED_SENSITIVE_VALUE = re.compile(
    rf"(?i)(?P<prefix>(?<![A-Za-z0-9-])[\"']?{_SENSITIVE_KEY}[\"']?\s*[:=]\s*)"
    r"(?P<value>(?:Bearer\s+)?[^\s,;&}\]\"']+)"
)
_BEARER_VALUE = re.compile(r"(?i)(?P<prefix>\bBearer\s+)(?P<value>\S+)")


def _redact_text(value: str) -> str:
    value = _QUOTED_SENSITIVE_VALUE.sub(
        lambda match: (
            f"{match.group('prefix')}{match.group('quote')}"
            f"{_REDACTED}{match.group('quote')}"
        ),
        value,
    )
    value = _UNQUOTED_SENSITIVE_VALUE.sub(
        lambda match: f"{match.group('prefix')}{_REDACTED}",
        value,
    )
    return _BEARER_VALUE.sub(
        lambda match: f"{match.group('prefix')}{_REDACTED}",
        value,
    )


def redact_log_value(value: object) -> object:
    if isinstance(value, str):
        return _redact_text(value)
    if isinstance(value, dict):
        return {
            key: (
                _REDACTED
                if isinstance(key, str) and _SENSITIVE_KEY_NAME.fullmatch(key)
                else redact_log_value(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [redact_log_value(item) for item in value]
    return value


class SensitiveDataFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = _redact_text(record.getMessage())
        record.args = ()
        if record.exc_info:
            traceback_text = logging.Formatter().formatException(record.exc_info)
            record.exc_text = _redact_text(traceback_text)
        return True


class JsonFormatter(logging.Formatter):
    _extra_fields = (
        "api_name",
        "request_time",
        "business_type",
        "success",
        "duration_ms",
        "environment",
        "event",
        "tenant_id",
        "shop_id",
        "platform_request_id",
        "result",
        "attempts",
        "error_code",
        "method",
        "path",
        "request_id",
        "records_read",
        "records_created",
        "records_updated",
        "notification_count",
        "status_code",
    )

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": _redact_text(record.getMessage()),
        }
        for field in self._extra_fields:
            value = getattr(record, field, None)
            if value is not None or (
                field == "status_code"
                and getattr(record, "event", None) == "feishu_api_call"
            ):
                payload[field] = redact_log_value(value)
        if "request_id" not in payload and (request_id := request_id_context.get()):
            payload["request_id"] = request_id
        if record.exc_info:
            payload["exception_type"] = record.exc_info[0].__name__
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(log_level: str) -> None:
    logger = logging.getLogger("erp_api")
    logger.setLevel(log_level.upper())
    logger.propagate = False

    for existing_handler in (*logging.getLogger().handlers, *logger.handlers):
        if not any(
            isinstance(log_filter, SensitiveDataFilter)
            for log_filter in existing_handler.filters
        ):
            existing_handler.addFilter(SensitiveDataFilter())

    if any(getattr(handler, "_erp_api_handler", False) for handler in logger.handlers):
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(SensitiveDataFilter())
    handler._erp_api_handler = True  # type: ignore[attr-defined]
    logger.addHandler(handler)
