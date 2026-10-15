from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import parse_qs, urlencode, urlsplit
from zoneinfo import ZoneInfo

from playwright.async_api import BrowserContext, Page

from backend.app.services.tiktok_affiliate_analytics_page_control import (
    PAGINATION_STATE_SCRIPT,
    RESOURCE_PAGE,
    matches_page,
    page_security_failure,
)
from backend.app.services.tiktok_affiliate_contract import platform_shop_id
from backend.app.services.tiktok_affiliate_creator_calendar import (
    select_creator_date as _select_creator_date,
)
from backend.app.services.tiktok_affiliate_intent_types import IntentPageError
from backend.app.services.tiktok_affiliate_response_probe import (
    probe_affiliate_page,
    trigger_probe_request,
)
from backend.app.services.tiktok_affiliate_scheduled_creator_page import (
    close_owned_page,
    is_scheduled_creator_intent,
    open_scheduled_creator_page,
)
from backend.app.services.tiktok_affiliate_video_window import (
    prepare_video_window_trigger,
)
from erp_api.services.affiliate_capture_intent_repository import (
    AffiliateCaptureIntent,
)
from erp_api.services.affiliate_center_contract import (
    AffiliateCenterQuery,
    AffiliateCenterResource,
)

_CREATOR_PAGE_URL = (
    "https://affiliate.tiktokshopglobalselling.com/data/creator-analysis"
)
_VIDEO_PAGE_URL = (
    "https://affiliate.tiktokshopglobalselling.com/affiliate/assets/video-analysis"
)
_VIDEO_PAGE_PATHS = frozenset(
    {"/affiliate/assets/video-analysis", "/insights/video-analysis"}
)
_RESOURCE_PAGE_URL = {
    "creators": _CREATOR_PAGE_URL,
    "videos": _VIDEO_PAGE_URL,
}
_US_RESOURCE_PATH = {
    "creators": "/data/creator-analysis",
    "videos": "/insights/video-analysis",
}
_RESPONSE_TIMEOUT_MS = 30_000
_CREATOR_WINDOW_ATTEMPTS = 3
_CREATOR_WINDOW_SETTLE_ATTEMPTS = 8
_CREATOR_WINDOW_SETTLE_SECONDS = 0.25
_probe_page = probe_affiliate_page
_trigger_probe_request = trigger_probe_request


def _max_browser_tabs() -> int:
    try:
        value = int(os.getenv("AFFILIATE_MAX_BROWSER_TABS", "8"))
    except ValueError:
        value = 8
    return min(30, max(2, value))


async def _no_op() -> None:
    return None


@dataclass(frozen=True)
class PreparedIntentPage:
    page: Page
    query: AffiliateCenterQuery
    trigger: Callable[[], Awaitable[None]]
    cleanup: Callable[[], Awaitable[None]] = _no_op


def intent_query(intent: AffiliateCaptureIntent) -> AffiliateCenterQuery:
    timezone = ZoneInfo(intent.shop_timezone)
    local_start = intent.window_start.astimezone(timezone).date()
    local_end = (
        (intent.window_end - timedelta(microseconds=1)).astimezone(timezone).date()
    )
    return AffiliateCenterQuery(
        resource=AffiliateCenterResource(intent.resource),
        shop_id=intent.shop_id,
        window_start=local_start,
        window_end=local_end,
        shop_timezone=intent.shop_timezone,
        currency=intent.currency,
        filters={},
    )


async def prepare_intent_page(
    contexts: Iterable[BrowserContext], intent: AffiliateCaptureIntent
) -> PreparedIntentPage:
    contexts = list(contexts)
    if is_scheduled_creator_intent(intent.resource, intent.job_id):
        owned_page = await open_scheduled_creator_page(
            contexts,
            intent.platform_shop_id,
            is_creator_page=lambda page: _is_intent_resource_page(
                page, RESOURCE_PAGE["creators"][0], "creators"
            ),
            security_check=page_security_failure,
            tab_limit=_max_browser_tabs(),
        )
        query = intent_query(intent)
        try:
            trigger = await _prepare_trigger(owned_page, query)
        except Exception:
            await close_owned_page(owned_page)
            raise

        async def cleanup() -> None:
            try:
                await getattr(trigger, "cleanup", _no_op)()
            finally:
                await close_owned_page(owned_page)

        return PreparedIntentPage(owned_page, query, trigger, cleanup)
    expected_path = RESOURCE_PAGE[intent.resource][0]
    pages = [
        page
        for context in contexts
        for page in context.pages
        if _is_intent_resource_page(page, expected_path, intent.resource)
    ]
    pages = await _ensure_resource_pages(
        contexts,
        pages,
        expected_path,
        intent.resource,
        platform_shop_id=intent.platform_shop_id,
    )
    if not pages:
        raise IntentPageError("target_page_missing")
    page, security = await _select_single_page(pages, intent.platform_shop_id)
    if security is not None:
        raise IntentPageError(security[1], page=page)
    query = intent_query(intent)
    if _page_shop_id(page) != intent.platform_shop_id:
        response = await _probe_page(page, intent.resource)
        if response.status == 403:
            raise IntentPageError("http_403", page=page)
        if response.status == 429:
            raise IntentPageError("rate_limited", page=page)
        if response.status == 401:
            raise IntentPageError("session_expired", page=page)
        if response.status != 200:
            raise IntentPageError("request_timeout", page=page)
        security = await page_security_failure(page)
        if security is not None:
            raise IntentPageError(security[1], page=page)
        if platform_shop_id(response.url) != intent.platform_shop_id:
            raise IntentPageError("target_page_missing", page=page)
    try:
        trigger = await _prepare_trigger(page, query)
    except IntentPageError as error:
        raise IntentPageError(error.category, page=page) from error
    cleanup = getattr(trigger, "cleanup", _no_op)
    return PreparedIntentPage(page, query, trigger, cleanup)


async def _select_single_page(
    pages: list[Page], platform_shop_id: str
) -> tuple[Page, tuple[str, str] | None]:
    ranked = []
    for index, page in enumerate(pages):
        security = await page_security_failure(page)
        try:
            focused = bool(await page.evaluate("document.hasFocus()"))
        except Exception:  # noqa: BLE001 -- fake, detached, or background page
            focused = False
        rank = (
            _page_shop_id(page) != platform_shop_id,
            security is not None,
            not focused,
            index,
        )
        ranked.append((rank, page, security))
    _, selected, security = min(ranked, key=lambda item: item[0])
    return selected, security


def _page_shop_id(page: Page) -> str | None:
    values = parse_qs(urlsplit(page.url).query).get("shop_id")
    return values[0] if values and values[0] else None


def browser_platform_shop_ids(pages: Iterable[Page]) -> frozenset[str]:
    resource_paths = {value[0] for value in RESOURCE_PAGE.values()} | _VIDEO_PAGE_PATHS
    return frozenset(
        shop_id
        for page in pages
        if urlsplit(page.url).path in resource_paths
        if (shop_id := _page_shop_id(page)) is not None
    )


def _is_intent_resource_page(
    page: Page,
    expected_path: str,
    resource: str,
) -> bool:
    if resource == "videos":
        return any(matches_page(page, path) for path in _VIDEO_PAGE_PATHS)
    if not matches_page(page, expected_path):
        return False
    if resource != "creators":
        return True
    return "creator_id" not in parse_qs(urlsplit(page.url).query)


async def _ensure_creator_pages(
    contexts: list[BrowserContext],
    pages: list[Page],
    expected_path: str,
) -> list[Page]:
    return await _ensure_resource_pages(
        contexts,
        pages,
        expected_path,
        "creators",
    )


async def _ensure_resource_pages(
    contexts: list[BrowserContext],
    pages: list[Page],
    expected_path: str,
    resource: str,
    *,
    created_pages: list[Page] | None = None,
    page_url: str | None = None,
    platform_shop_id: str | None = None,
) -> list[Page]:
    candidates = list(pages)
    tab_limit_reached = False
    session_expired = False
    for context in contexts:
        if any(
            _is_intent_resource_page(page, expected_path, resource)
            for page in context.pages
        ):
            continue
        if len(context.pages) >= _max_browser_tabs():
            tab_limit_reached = True
            continue
        page = None
        try:
            page = await context.new_page()
            await page.goto(
                page_url or _resource_page_url([context], resource, platform_shop_id),
                wait_until="domcontentloaded",
                timeout=_RESPONSE_TIMEOUT_MS,
            )
            if not _is_intent_resource_page(page, expected_path, resource):
                session_expired = _is_auth_redirect(page.url) or session_expired
                await _close_page(page)
                continue
        except Exception:  # noqa: BLE001 -- try the next browser context
            if page is not None:
                await _close_page(page)
            continue
        candidates.append(page)
        if created_pages is not None:
            created_pages.append(page)
    if not candidates and session_expired:
        raise IntentPageError("session_expired")
    if not candidates and tab_limit_reached:
        raise IntentPageError("tab_limit_reached")
    return candidates


def _resource_page_url(
    contexts: Iterable[BrowserContext],
    resource: str,
    platform_shop_id: str | None,
) -> str:
    if platform_shop_id and any(
        urlsplit(page.url).hostname == "affiliate-us.tiktok.com"
        for context in contexts
        for page in context.pages
    ):
        query = urlencode({"shop_region": "US", "shop_id": platform_shop_id}, safe="")
        return f"https://affiliate-us.tiktok.com{_US_RESOURCE_PATH[resource]}?{query}"
    return _RESOURCE_PAGE_URL[resource]


def _is_auth_redirect(url: str) -> bool:
    split = urlsplit(url)
    if split.hostname == "www.tiktok.com" and split.path.startswith("/ucenter_web/"):
        return True
    return (
        split.hostname == "seller.tiktokshopglobalselling.com"
        and split.path.startswith("/account/")
    )


async def _close_page(page: Page) -> None:
    try:
        await page.close()
    except Exception:  # noqa: BLE001,S110 -- a detached page is already closed
        pass


async def _trigger_creator_first_page(page: Page) -> None:
    locator = page.locator(RESOURCE_PAGE["creators"][1])
    items = await locator.evaluate_all(PAGINATION_STATE_SCRIPT)
    first_page_index = _page_index(items, 1)
    if first_page_index is None:
        raise IntentPageError("request_timeout")
    await locator.nth(first_page_index).evaluate("(element) => element.click()")


async def _trigger_video_first_page(page: Page) -> None:
    locator = page.locator(RESOURCE_PAGE["videos"][1])
    items = await locator.evaluate_all(PAGINATION_STATE_SCRIPT)
    first_page_index = _page_index(items, 1)
    if first_page_index is None:
        raise IntentPageError("request_timeout")
    await locator.nth(first_page_index).evaluate("(element) => element.click()")


def _page_index(items: object, page_number: int) -> int | None:
    if not isinstance(items, list):
        return None
    for index, item in enumerate(items):
        if isinstance(item, dict) and item.get("text") == str(page_number):
            return index
    return None


async def _prepare_trigger(
    page: Page, query: AffiliateCenterQuery
) -> Callable[[], Awaitable[None]]:
    if query.resource is AffiliateCenterResource.VIDEOS:
        if urlsplit(getattr(page, "url", "")).hostname == "affiliate-us.tiktok.com":
            return await prepare_video_window_trigger(page, query)
        return _no_op
    await _select_creator_window(page, query.window_start, query.window_end)

    async def trigger() -> None:
        try:
            await _trigger_creator_first_page(page)
        except IntentPageError as error:
            if error.category != "request_timeout":
                raise
            await _select_creator_window(page, query.window_start, query.window_end)

    return trigger


async def _select_creator_window(page: Page, start, end) -> None:
    picker = page.locator(".m4b-date-picker-range")
    expected = [start.isoformat(), end.isoformat()]
    last_error: Exception | None = None
    for attempt in range(_CREATOR_WINDOW_ATTEMPTS):
        try:
            await picker.wait_for(state="visible", timeout=_RESPONSE_TIMEOUT_MS)
            if await _creator_window_values(picker) == expected:
                return
            await page.keyboard.press("Escape")
            await picker.click()
            await _select_creator_date(page, start)
            await _select_creator_date(page, end)
            if await _creator_window_settled(picker, expected):
                return
            last_error = IntentPageError("window_mismatch")
        except Exception as error:  # noqa: BLE001 -- the UI may settle after timeout
            last_error = error
            if await _creator_window_settled(picker, expected):
                return
        if attempt + 1 < _CREATOR_WINDOW_ATTEMPTS:
            await asyncio.sleep(_CREATOR_WINDOW_SETTLE_SECONDS)
    if isinstance(last_error, IntentPageError):
        raise last_error
    raise IntentPageError("window_not_settable") from last_error


async def _creator_window_values(picker) -> list[str]:
    inputs = picker.locator("input")
    return [await inputs.nth(index).input_value() for index in (0, 1)]


async def _creator_window_settled(picker, expected: list[str]) -> bool:
    for attempt in range(_CREATOR_WINDOW_SETTLE_ATTEMPTS):
        try:
            if await _creator_window_values(picker) == expected:
                return True
        except Exception:  # noqa: BLE001,S110 -- transient UI state is retried
            pass
        if attempt + 1 < _CREATOR_WINDOW_SETTLE_ATTEMPTS:
            await asyncio.sleep(_CREATOR_WINDOW_SETTLE_SECONDS)
    return False


