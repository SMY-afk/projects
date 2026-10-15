import json
from datetime import UTC, datetime

from erp_api.core.logging import redact_log_value


def capture_log(event: str, **values: object) -> None:
    safe_values = redact_log_value(values)
    if not isinstance(safe_values, dict):
        raise TypeError("Capture log values must remain a mapping.")
    print(
        json.dumps(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "event": event,
                **safe_values,
            },
            ensure_ascii=False,
            default=str,
        ),
        flush=True,
    )


def safe_error(error: Exception) -> str:
    message = str(redact_log_value(str(error).strip()))
    return message[:500] or type(error).__name__
