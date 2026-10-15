from __future__ import annotations

import logging
import re
from typing import Any

_SAFE_ERROR_CODE = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")


def log_sample_sync_success(
    logger: logging.Logger,
    *,
    tenant_id: str,
    shop_id: str,
    request_id: str,
    duration_ms: float,
    result: object,
) -> None:
    source_results = getattr(result, "source_results", ())
    feishu_result = getattr(result, "feishu_result", None)
    logger.info(
        "sample_sync_succeeded",
        extra={
            "event": "sample_sync_succeeded",
            "tenant_id": tenant_id,
            "shop_id": shop_id,
            "request_id": request_id,
            "records_read": sum(
                _count(item, "record_count") for item in source_results
            ),
            "records_created": _count(feishu_result, "created_count"),
            "records_updated": _count(feishu_result, "updated_count"),
            "notification_count": len(
                getattr(result, "notification_results", ()) or ()
            ),
            "duration_ms": round(duration_ms, 2),
        },
    )


def log_sample_sync_failure(
    logger: logging.Logger,
    *,
    tenant_id: str,
    shop_id: str,
    request_id: str,
    duration_ms: float,
    error: Exception,
) -> None:
    logger.warning(
        "sample_sync_failed",
        extra={
            "event": "sample_sync_failed",
            "tenant_id": tenant_id,
            "shop_id": shop_id,
            "request_id": request_id,
            "duration_ms": round(duration_ms, 2),
            "error_code": safe_sample_error_code(error),
        },
    )


def safe_sample_error_code(error: Exception) -> str:
    for attribute in ("code", "error_code"):
        value = getattr(error, attribute, None)
        if isinstance(value, str) and _SAFE_ERROR_CODE.fullmatch(value):
            return value
    return type(error).__name__[:64]


def _count(value: Any, attribute: str) -> int:
    count = getattr(value, attribute, 0)
    return count if isinstance(count, int) and count >= 0 else 0
