from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from erp_api.services.tiktok_transport import (
    TikTokApiError,
    TikTokClientError,
    TikTokRateLimitError,
    TikTokTimeoutError,
)

AnalyticsErrorCategory = Literal[
    "invalid_response",
    "missing_field",
    "platform_error",
    "rate_limited",
    "timeout",
    "transport_error",
]


@dataclass(frozen=True)
class TikTokAnalyticsItem:
    fields: dict[str, Any]
    source_status: str | None
    status: str | None
    source_updated_at: datetime | None


@dataclass(frozen=True)
class TikTokAnalyticsPage:
    items: list[TikTokAnalyticsItem]
    next_page_token: str | None
    platform_request_id: str | None
    source_updated_at: datetime | None
    raw_payload: dict[str, Any]


@dataclass(frozen=True)
class TikTokAnalyticsFailure:
    category: AnalyticsErrorCategory
    platform_request_id: str | None
    retry_after_seconds: float | None = None


def parse_analytics_page(
    payload: Mapping[str, Any],
    *,
    platform_request_id: str | None,
    items_path: str,
    next_page_token_path: str | None,
    field_map: Mapping[str, str],
    required_fields: tuple[str, ...],
    source_updated_at_path: str | None,
    item_source_updated_at_path: str | None,
    status_path: str | None,
    status_map: Mapping[str, str],
    empty_data_as_empty_page: bool = False,
) -> TikTokAnalyticsPage:
    data = payload.get("data", payload)
    if not isinstance(data, Mapping):
        raise _invalid(
            "Analytics response did not contain a data object.", platform_request_id
        )
    raw_items = _get_path(data, items_path)
    if raw_items is None and empty_data_as_empty_page and not data:
        raw_items = []
    if not isinstance(raw_items, list) or any(
        not isinstance(item, Mapping) for item in raw_items
    ):
        raise _invalid(
            "Analytics response did not contain a valid items list.",
            platform_request_id,
        )
    next_page_token = _get_path(data, next_page_token_path)
    if next_page_token is not None and not isinstance(next_page_token, str):
        raise _invalid(
            "Analytics response contained an invalid page token.", platform_request_id
        )
    return TikTokAnalyticsPage(
        items=[
            _parse_item(
                item,
                field_map=field_map,
                required_fields=required_fields,
                item_source_updated_at_path=item_source_updated_at_path,
                status_path=status_path,
                status_map=status_map,
                platform_request_id=platform_request_id,
            )
            for item in raw_items
        ],
        next_page_token=next_page_token,
        platform_request_id=platform_request_id,
        source_updated_at=_timestamp_or_none(
            _get_path(data, source_updated_at_path), platform_request_id
        ),
        raw_payload=dict(payload),
    )


def classify_analytics_failure(error: TikTokClientError) -> TikTokAnalyticsFailure:
    if isinstance(error, TikTokRateLimitError):
        return TikTokAnalyticsFailure(
            "rate_limited", error.request_id, error.retry_after_seconds
        )
    if isinstance(error, TikTokTimeoutError):
        return TikTokAnalyticsFailure("timeout", None)
    if isinstance(error, TikTokApiError):
        category: AnalyticsErrorCategory = (
            "missing_field"
            if error.code == "missing_analytics_field"
            else "platform_error"
        )
        if error.code == "invalid_analytics_response":
            category = "invalid_response"
        return TikTokAnalyticsFailure(category, error.request_id)
    return TikTokAnalyticsFailure("transport_error", None)


def _parse_item(
    item: Mapping[str, Any],
    *,
    field_map: Mapping[str, str],
    required_fields: tuple[str, ...],
    item_source_updated_at_path: str | None,
    status_path: str | None,
    status_map: Mapping[str, str],
    platform_request_id: str | None,
) -> TikTokAnalyticsItem:
    fields = {name: _get_path(item, path) for name, path in field_map.items()}
    if any(fields.get(name) is None for name in required_fields):
        raise TikTokApiError(
            "Analytics response missed required fields.",
            code="missing_analytics_field",
            status_code=502,
            request_id=platform_request_id,
        )
    source_status = _get_path(item, status_path)
    if source_status is not None and not isinstance(source_status, str):
        raise _invalid(
            "Analytics response contained an invalid status.", platform_request_id
        )
    return TikTokAnalyticsItem(
        fields=fields,
        source_status=source_status,
        status=None
        if source_status is None
        else status_map.get(source_status, "unknown"),
        source_updated_at=_timestamp_or_none(
            _get_path(item, item_source_updated_at_path), platform_request_id
        ),
    )


def _get_path(value: Mapping[str, Any], path: str | None) -> Any:
    if not path:
        return None

    current: Any = value
    for segment in path.split("."):
        if not isinstance(current, Mapping):
            return None
        current = current.get(segment)
    return current


def _timestamp_or_none(value: Any, platform_request_id: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, tz=UTC)
        if isinstance(value, str) and value.isdigit():
            return datetime.fromtimestamp(int(value), tz=UTC)
        if isinstance(value, str):
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is not None:
                return parsed.astimezone(UTC)
    except (OverflowError, OSError, ValueError):
        pass
    raise _invalid(
        "Analytics response contained an invalid source timestamp.", platform_request_id
    )


def _invalid(message: str, platform_request_id: str | None) -> TikTokApiError:
    return TikTokApiError(
        message,
        code="invalid_analytics_response",
        status_code=502,
        request_id=platform_request_id,
    )
