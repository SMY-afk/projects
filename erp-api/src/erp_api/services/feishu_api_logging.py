from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from urllib.parse import urlsplit

logger = logging.getLogger("erp_api.feishu_api")


def request_started() -> tuple[str, float]:
    return datetime.now(UTC).isoformat(timespec="milliseconds"), time.perf_counter()


def log_api_call(
    method: str,
    path: str,
    *,
    business_type: str,
    request_time: str,
    started_at: float,
    status_code: int | None,
    success: bool,
) -> None:
    api_route = _api_route(path)
    logger.info(
        "Feishu API call",
        extra={
            "event": "feishu_api_call",
            "api_name": f"{method.upper()} {api_route}",
            "request_time": request_time,
            "business_type": (
                "authentication"
                if api_route == "auth.tenant_access_token"
                else business_type
            ),
            "status_code": status_code,
            "duration_ms": round((time.perf_counter() - started_at) * 1000, 2),
            "success": success,
        },
    )


def _api_route(path: str) -> str:
    parts = urlsplit(path).path.strip("/").split("/")
    if parts == ["open-apis", "auth", "v3", "tenant_access_token", "internal"]:
        return "auth.tenant_access_token"
    if (
        len(parts) >= 8
        and parts[:3] == ["open-apis", "bitable", "v1"]
        and parts[3] == "apps"
        and parts[5] == "tables"
        and parts[7] in {"records", "fields"}
    ):
        action = "list"
        if len(parts) > 8:
            action = (
                parts[8]
                if parts[8]
                in {"batch_create", "batch_update", "batch_delete", "search"}
                else "item"
            )
        return f"bitable.{parts[7]}.{action}"
    if parts[:3] == ["open-apis", "im", "v1"] and len(parts) >= 4:
        if parts[3] == "messages":
            return "im.messages.item" if len(parts) > 4 else "im.messages.create"
        if parts[3] == "images":
            return "im.images.create"
    if (
        parts[:3]
        in (
            ["open-apis", "sheets", "v2"],
            ["open-apis", "sheets", "v3"],
        )
        and "spreadsheets" in parts
    ):
        return "sheets.query" if parts[-1] == "query" else "sheets.values"
    return "other"
