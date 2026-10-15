from __future__ import annotations

from collections.abc import Iterable, Mapping

from erp_api.services.affiliate_center_capture_policy import sanitize_capture_payload
from erp_api.services.affiliate_center_contract import (
    AffiliateCenterQuery,
    AffiliateCenterResource,
)


def query_context(
    query: AffiliateCenterQuery, resource: AffiliateCenterResource
) -> dict[str, object]:
    if query.resource != resource:
        raise ValueError(f"query.resource must be {resource.value}")
    window_start_utc, window_end_utc = query.utc_window()
    return {
        "window_start_utc": window_start_utc,
        "window_end_utc": window_end_utc,
        "shop_timezone": query.shop_timezone,
        "currency": query.currency,
    }


def source_identifiers(**values: str | None) -> dict[str, str]:
    return {key: value for key, value in values.items() if value}


def extensions(
    value: Mapping[str, object], confirmed_fields: Iterable[str]
) -> dict[str, object]:
    confirmed = set(confirmed_fields)
    candidate = {key: item for key, item in value.items() if key not in confirmed}
    sanitized = sanitize_capture_payload(candidate)
    if not isinstance(sanitized, dict):
        raise TypeError("sanitized extensions must be an object")
    return sanitized


def grouped_extensions(
    sections: Mapping[str, tuple[Mapping[str, object], Iterable[str]]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for name, (value, confirmed_fields) in sections.items():
        extra = extensions(value, confirmed_fields)
        if extra:
            result[name] = extra
    return result
