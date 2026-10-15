from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping

from playwright.async_api import Page, Response

from backend.app.services.tiktok_affiliate_analytics_page_control import (
    PAGINATION_STATE_SCRIPT,
    current_and_next,
    page_security_failure,
)
from erp_api.services.affiliate_creator_detail_parser import (
    creator_detail_request_params,
)

TAB_RESOURCES = ("video", "live", "product", "product_card")


async def advance_detail_page(
    page: Page, expected_page: int
) -> tuple[bool, str | None]:
    failure = await page_security_failure(page)
    if failure is not None:
        return False, failure[1]
    locator = page.locator(".kora-pagination-item:visible")
    items = await locator.evaluate_all(PAGINATION_STATE_SCRIPT)
    current, next_index = current_and_next(items)
    if current != expected_page or next_index is None:
        return False, "cursor_interrupted"
    await locator.nth(next_index).click()
    return True, None


async def drive_detail_tabs(
    page: Page,
    events: dict[tuple[int, str], asyncio.Event],
    max_runtime: float,
    failure_handler: Callable[[Page, str, str], Awaitable[None]],
) -> None:
    tabs = page.locator('[role="tab"]')
    if await tabs.count() < len(TAB_RESOURCES):
        return
    for index, kind in enumerate(TAB_RESOURCES):
        if page.is_closed():
            return
        locator = tabs.nth(index)
        key = (id(page), kind)
        event = events.setdefault(key, asyncio.Event())
        event.clear()
        try:
            if await locator.get_attribute("aria-selected") != "true":
                await locator.click()
            if index == 0:
                await page.wait_for_timeout(800)
                await _load_first_video_page(page)
            await asyncio.wait_for(event.wait(), timeout=max_runtime)
        except TimeoutError:
            await failure_handler(page, kind, "request_timeout")
            return


async def _load_first_video_page(page: Page) -> None:
    pagination = page.locator(".kora-pagination-item:visible")
    items = await pagination.evaluate_all(PAGINATION_STATE_SCRIPT)
    current, _ = current_and_next(items)
    if current == 1:
        await page.reload(wait_until="domcontentloaded")
        return
    for index, item in enumerate(items):
        if isinstance(item, Mapping) and item.get("text") == "1":
            await pagination.nth(index).click()
            return
    await page.reload(wait_until="domcontentloaded")


async def select_first_detail_page(page: Page) -> bool:
    pagination = page.locator(".kora-pagination-item:visible")
    items = await pagination.evaluate_all(PAGINATION_STATE_SCRIPT)
    for index, item in enumerate(items):
        if isinstance(item, Mapping) and item.get("text") == "1":
            await pagination.nth(index).click()
            return True
    return False


def approved_filters(body: Mapping[str, object]) -> dict[str, object]:
    source = creator_detail_request_params(body).get("filter")
    if not isinstance(source, Mapping):
        return {}
    allowlist = {
        "only_sample",
        "content_type",
        "filter_type",
        "list_type",
        "sort_field",
        "sort_order",
    }
    return {key: source[key] for key in allowlist if key in source}


def response_page(response: Response) -> Page | None:
    try:
        return response.request.frame.page
    except Exception:  # noqa: BLE001 -- service worker response
        return None


async def request_id(response: Response) -> str | None:
    for name in ("request-id", "x-request-id", "x-tt-logid", "x-tt-trace-id"):
        value = await response.header_value(name)
        if value:
            return value[:128]
    return None


def http_failure(status: int) -> str:
    return {401: "session_expired", 403: "http_403", 429: "rate_limited"}[status]
