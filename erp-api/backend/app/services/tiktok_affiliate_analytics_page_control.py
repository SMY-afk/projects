from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import urlsplit

from playwright.async_api import Page

from backend.app.services.capture_logging import capture_log as _log
from erp_api.services.affiliate_center_capture_policy import (
    validate_capture_log_fields,
)

AFFILIATE_HOSTS = frozenset(
    {"affiliate.tiktokshopglobalselling.com", "affiliate-us.tiktok.com"}
)
RESOURCE_PAGE = {
    "creators": ("/data/creator-analysis", ".kora-pagination-item"),
    "videos": ("/affiliate/assets/video-analysis", ".core-pagination-item"),
}
RESOURCE_ENDPOINT = {
    "creators": "/api/v2/insights/affiliate/seller/creator/filter_list",
    "videos": "/api/v1/oec/affiliate/compass/transaction/detail_list/get",
}
PAGINATION_STATE_SCRIPT = """elements => elements.map(element => ({
    text: (element.textContent || '').trim(),
    className: String(element.className || ''),
    ariaCurrent: element.getAttribute('aria-current'),
    ariaDisabled: element.getAttribute('aria-disabled')
}))"""
_CAPTCHA_SELECTOR = 'iframe[src*="captcha" i], [id*="captcha" i], [class*="captcha" i]'
_SESSION_PATH_MARKERS = ("/login", "/passport", "/signin", "/auth/")


def matches_page(page: Page, expected_path: str) -> bool:
    split = urlsplit(page.url)
    if not is_affiliate_host(split.hostname):
        return False
    if split.path == expected_path:
        return True
    return (
        expected_path == RESOURCE_PAGE["videos"][0]
        and split.hostname == "affiliate-us.tiktok.com"
        and split.path == "/insights/video-analysis"
    )


def is_affiliate_host(hostname: str | None) -> bool:
    return (hostname or "").casefold() in AFFILIATE_HOSTS


def matches_observation(resource: str, observation: Mapping[str, object]) -> bool:
    return (
        is_affiliate_host(str(observation.get("host") or ""))
        and observation.get("method") == "POST"
        and observation.get("path") == RESOURCE_ENDPOINT.get(resource)
        and isinstance(observation.get("payloadDiscriminator"), str)
    )


def safe_request_template(
    resource: str,
    observation: Mapping[str, object],
    page_path: str,
) -> dict[str, str]:
    return {
        "resource": resource,
        "host": str(observation["host"]),
        "method": str(observation["method"]),
        "path": str(observation["path"]),
        "pagePath": page_path,
        "triggerMode": "page_control",
    }


def current_and_next(items: object) -> tuple[int | None, int | None]:
    if not isinstance(items, list):
        return None, None
    current_page: int | None = None
    numeric_items: list[tuple[int, int]] = []
    for index, item in enumerate(items):
        if not isinstance(item, Mapping):
            continue
        text = item.get("text")
        if not isinstance(text, str) or not text.isdecimal():
            continue
        page_number = int(text)
        numeric_items.append((page_number, index))
        class_name = item.get("className")
        if item.get("ariaCurrent") == "true" or (
            isinstance(class_name, str) and "pagination-item-active" in class_name
        ):
            current_page = page_number
    if current_page is None:
        return None, None
    next_index = next(
        (
            index
            for page_number, index in numeric_items
            if page_number == current_page + 1
        ),
        None,
    )
    return current_page, next_index


async def page_security_failure(page: Page) -> tuple[str, str] | None:
    path = urlsplit(page.url).path.casefold()
    if "captcha" in path:
        return "session_required", "captcha"
    if any(marker in path for marker in _SESSION_PATH_MARKERS):
        return "session_required", "session_expired"
    try:
        captcha_nodes = page.locator(_CAPTCHA_SELECTOR)
        for index in range(await captcha_nodes.count()):
            if await captcha_nodes.nth(index).is_visible():
                return "session_required", "captcha"
    except Exception as error:
        raise RuntimeError("page_security_probe_failed") from error
    return None


def pagination_mode(observation: Mapping[str, object]) -> object:
    pagination = observation.get("pagination")
    return pagination.get("mode") if isinstance(pagination, Mapping) else None


def capture_log(event: str, **values: object) -> None:
    safe = validate_capture_log_fields({"event": event, **values})
    safe.pop("event")
    _log(event, **safe)
