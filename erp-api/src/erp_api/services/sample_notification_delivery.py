from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import UUID

RETRYABLE_FEISHU_CODES = {
    "transport_error",
    "timeout",
    "http_429",
    "1254002",
    "99991400",
    "http_408",
}


def build_shop_record_url_templates(
    record_url_template: str,
    table_ids_by_shop: Mapping[UUID, str],
) -> dict[UUID, str]:
    """Point each shop's card link at the same table used for its projection."""
    parsed = urlsplit(record_url_template)
    base_query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key not in {"table", "view"}
    ]
    return {
        shop_id: urlunsplit(
            parsed._replace(
                query=urlencode(
                    [("table", table_id), *base_query],
                    safe="{}",
                )
            )
        )
        for shop_id, table_id in table_ids_by_shop.items()
    }


def is_retryable_notification_error(code: str) -> bool:
    return code in RETRYABLE_FEISHU_CODES or code.startswith("http_5")


def safe_notification_error_code(code: str) -> str:
    if code in {
        *RETRYABLE_FEISHU_CODES,
        "invalid_response",
        "invalid_notification_payload",
        "creator_profile_incomplete",
        "creator_profile_stale",
        "notification_source_incomplete",
        "product_image_unavailable",
        "sample_assignment_projection_missing",
    }:
        return code
    if re.fullmatch(r"http_[1-5][0-9]{2}", code) or re.fullmatch(r"[0-9]{5,10}", code):
        return code
    return "feishu_error"


def delivery_evidence(
    payload: dict[str, object],
    *,
    message_key: str = "message_id",
    sent_at_key: str = "message_sent_at",
) -> tuple[str | None, datetime | None]:
    message_id = payload.get(message_key)
    sent_at = payload.get(sent_at_key)
    if message_id is None and sent_at is None:
        return None, None
    if not isinstance(message_id, str) or not isinstance(sent_at, str):
        raise TypeError("Sample notification delivery evidence is invalid.")
    parsed = datetime.fromisoformat(sent_at)
    if parsed.tzinfo is None:
        raise ValueError("Sample notification delivery time is invalid.")
    return message_id, parsed.astimezone(UTC)
