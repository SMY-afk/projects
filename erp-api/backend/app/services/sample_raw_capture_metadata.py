from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass

from playwright.async_api import Response

from backend.app.services.hubstudio_sample_network_listener import (
    _allowed_response_headers,
    _body_request_id,
    _first_request_id,
)
from backend.app.services.sample_raw_batch_validation import (
    RAW_CURSOR_KEYS as _CURSOR_KEYS,
)
from backend.app.services.sample_raw_batch_validation import (
    RAW_PAGE_KEYS as _PAGE_KEYS,
)
from backend.app.services.sample_raw_batch_validation import validate_initial_cursor
from erp_api.services.tiktok_sample_application_payload import (
    TikTokSampleApplicationPage,
)


@dataclass(frozen=True)
class SampleRawRequestMarker:
    page: int | None
    cursor: str


@dataclass(frozen=True)
class SampleRawResponseMetadata:
    request_id: str
    has_more: bool
    total_count: int | None


def parse_request_marker(post_data: str | None, fallback_page: int) -> SampleRawRequestMarker:
    try:
        payload = json.loads(post_data or "")
    except (TypeError, ValueError) as error:
        raise ValueError("RAW sample request body is invalid") from error
    if not isinstance(payload, Mapping):
        raise TypeError("RAW sample request body is invalid")
    marker = _pagination_markers(payload)
    page_values = {
        value
        for path, value in marker
        if path.rsplit(".", 1)[-1] in _PAGE_KEYS
        and isinstance(value, int)
        and not isinstance(value, bool)
        and value >= 0
    }
    if len(page_values) > 1:
        raise RuntimeError("RAW sample request page marker is ambiguous")
    if not page_values or min(page_values) < 1:
        raise RuntimeError("RAW sample request page marker is missing or invalid")
    page = next(iter(page_values))
    cursor = json.dumps(marker, ensure_ascii=True, separators=(",", ":"))
    if page == 1:
        validate_initial_cursor(cursor)
    return SampleRawRequestMarker(page, cursor)


def parse_capture_request_marker(post_data: str | None, expected_page: int):
    try:
        marker = parse_request_marker(post_data, expected_page)
        if marker.page != expected_page:
            raise RuntimeError("RAW sample request pages are not contiguous; must start at 1")
        return marker
    except (RuntimeError, TypeError, ValueError) as error:
        return error


def _pagination_markers(
    value: object, path: tuple[str, ...] = ()
) -> list[list[str | int]]:
    markers: list[list[str | int]] = []
    if isinstance(value, Mapping):
        for raw_key, child in value.items():
            key = str(raw_key)
            child_path = (*path, key)
            if (
                key in (*_PAGE_KEYS, *_CURSOR_KEYS)
                and isinstance(child, (str, int))
            ):
                markers.append([".".join(child_path), child])
            markers.extend(_pagination_markers(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            markers.extend(_pagination_markers(child, (*path, str(index))))
    return markers


async def read_response_metadata(
    response: Response, payload: Mapping[str, object]
) -> SampleRawResponseMetadata:
    headers = await _allowed_response_headers(response)
    request_id = _first_request_id(headers) or _body_request_id(payload)
    if request_id is None:
        raise RuntimeError("RAW sample response request id is missing")
    has_more = payload.get("has_more")
    total_count = payload.get("total_count")
    if not isinstance(has_more, bool) or (
        total_count is not None
        and (
            not isinstance(total_count, int)
            or isinstance(total_count, bool)
            or total_count < 0
        )
    ):
        raise RuntimeError("RAW sample response pagination metadata is invalid")
    return SampleRawResponseMetadata(request_id, has_more, total_count)


def validate_captured_pages(
    pages: list[TikTokSampleApplicationPage],
) -> tuple[int | None, int]:
    if not pages or pages[-1].next_page_token is not None:
        raise RuntimeError("RAW sample terminal page is not confirmed")
    if any(page.next_page_token is None for page in pages[:-1]):
        raise RuntimeError("RAW sample pagination terminated before the final page")
    totals = {page.total_count for page in pages if page.total_count is not None}
    if len(totals) > 1:
        raise RuntimeError("RAW sample expected total changed between pages")
    expected_total = next(iter(totals), None)
    application_ids = {
        str(application["id"])
        for page in pages
        for application in page.applications
    }
    captured_total = len(application_ids)
    if expected_total is not None and expected_total != captured_total:
        raise RuntimeError("RAW sample captured total does not match expected total")
    return expected_total, captured_total
