from __future__ import annotations

import asyncio
import re
from collections.abc import Iterable, Sequence
from datetime import date
from urllib.parse import parse_qs, urlencode, urlsplit

from playwright.async_api import BrowserContext, Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from backend.app.services.tiktok_affiliate_analytics_page_control import (
    is_affiliate_host,
    matches_page,
    page_security_failure,
)
from backend.app.services.tiktok_affiliate_export_picker_date import (
    detect_video_export_picker_day,
)
from backend.app.services.tiktok_affiliate_video_available_date import (
    detect_video_api_latest_day,
)

_PAGE_URL = {
    "creators": "https://affiliate.tiktokshopglobalselling.com/data/creator-analysis",
    "videos": "https://affiliate.tiktokshopglobalselling.com/insights/video-analysis",
}
_PAGE_PATHS = {
    "creators": ("/data/creator-analysis",),
    "videos": ("/insights/video-analysis", "/affiliate/assets/video-analysis"),
}
_MONTH = re.compile(r"(\d{4})\D+(\d{1,2})\D*")
_US_MONTH = re.compile(r"(\d{1,2})\D+(\d{4})\D*")
_DATE_TOKEN = r"(?:\d{4}/\d{1,2}/\d{1,2}|\d{1,2}/\d{1,2}/\d{4})"
_VIDEO_RANGE = re.compile(rf"^{_DATE_TOKEN}\s*-\s*{_DATE_TOKEN}$")
RESOURCE_PROBE_TIMEOUT_SECONDS = 35.0
PAGE_NAVIGATION_TIMEOUT_MS = 8_000
PAGE_CLOSE_TIMEOUT_SECONDS = 2.0


def latest_date_from_panels(
    panels: Iterable[tuple[str, Sequence[str]]],
) -> date | None:
    candidates: list[date] = []
    for month_label, days in panels:
        match = _MONTH.fullmatch(month_label.strip())
        if match is not None:
            year, month = map(int, match.groups())
        else:
            us_match = _US_MONTH.fullmatch(month_label.strip())
            if us_match is None:
                continue
            month, year = map(int, us_match.groups())
        for day_label in days:
            try:
                candidates.append(date(year, month, int(day_label.strip())))
            except (TypeError, ValueError):
                continue
    return max(candidates) if candidates else None


async def detect_latest_selectable_dates(
    contexts: Iterable[BrowserContext],
    resources: Sequence[str] = ("creators", "videos"),
    *,
    resource_timeout_seconds: float = RESOURCE_PROBE_TIMEOUT_SECONDS,
) -> dict[str, date]:
    if resource_timeout_seconds <= 0:
        raise ValueError("Resource availability timeout must be positive.")
    available: dict[str, date] = {}
    context_list = list(contexts)
    for resource in resources:
        if resource not in _PAGE_URL:
            raise ValueError(f"Unsupported affiliate resource: {resource}")
        try:
            latest = await asyncio.wait_for(
                _detect_resource_date(context_list, resource),
                timeout=resource_timeout_seconds,
            )
        except TimeoutError:
            latest = None
        if latest is not None:
            available[resource] = latest
    return available


async def _detect_resource_date(
    contexts: list[BrowserContext], resource: str
) -> date | None:
    if resource == "videos":
        current_pages = [
            (context, page_url)
            for context in contexts
            if (page_url := _resource_url([context], resource))
            and parse_qs(urlsplit(page_url).query).get("shop_id")
        ]
        if current_pages:
            for context, page_url in current_pages:
                latest = await detect_video_export_picker_day(
                    context, page_url, _detect_page_date
                )
                if latest is not None:
                    return latest
                latest = await detect_video_api_latest_day(context, page_url)
                if latest is not None:
                    return latest
            return None
    page, temporary = await _resource_page(contexts, resource)
    try:
        return await _detect_page_date(page, resource, refresh=not temporary)
    finally:
        if temporary and page is not None:
            await _close_page(page)


async def _detect_page_date(
    page: Page | None, resource: str, *, refresh: bool = True
) -> date | None:
    if page is None or await page_security_failure(page) is not None:
        return None
    try:
        if refresh:
            try:
                await page.reload(
                    wait_until="domcontentloaded",
                    timeout=PAGE_NAVIGATION_TIMEOUT_MS,
                )
            except (TimeoutError, PlaywrightTimeoutError):
                pass
        if await page_security_failure(page) is not None:
            return None
        if resource == "creators":
            picker = page.locator(".m4b-date-picker-range")
            await picker.wait_for(state="visible", timeout=10_000)
            await picker.click()
            trigger = page.locator(".m4b-date-picker-range-trigger")
            panel_selector = ".arco-panel-date-inner"
            month_selector = ".arco-picker-header-value"
            cell_selector = ".arco-picker-cell-in-view:not(.arco-picker-cell-disabled)"
            await trigger.wait_for(state="visible", timeout=10_000)
            panels = trigger.locator(panel_selector)
        else:
            panel_selector = ".core-panel-date"
            month_selector = ".core-picker-header-value"
            cell_selector = ".core-picker-cell-in-view:not(.core-picker-cell-disabled)"
            try:
                current_picker = page.locator(".pulse-date-picker-range")
                await current_picker.first.wait_for(state="visible", timeout=10_000)
                await current_picker.first.click()
                panels = page.locator(f"{panel_selector}:visible")
                await panels.first.wait_for(state="visible", timeout=10_000)
                await page.locator(
                    f"{panel_selector}:visible {cell_selector}"
                ).first.wait_for(state="visible", timeout=10_000)
            except Exception:  # noqa: BLE001 -- support the previous video page
                await page.get_by_text(_VIDEO_RANGE, exact=True).first.click()
                await page.locator(
                    ".core-dropdown:visible div.cursor-pointer"
                ).last.click()
                trigger = page.locator("[class*='rangePickerScoped']:visible")
                await trigger.wait_for(state="visible", timeout=10_000)
                panels = trigger.locator(panel_selector)
        values = []
        for index in range(await panels.count()):
            panel = panels.nth(index)
            month = (await panel.locator(month_selector).inner_text()).strip()
            days = await panel.locator(cell_selector).all_text_contents()
            values.append((month, days))
        return latest_date_from_panels(values)
    except Exception:  # noqa: BLE001 -- live page shape and session boundary
        return None
    finally:
        try:
            await page.keyboard.press("Escape")
        except Exception:  # noqa: BLE001,S110 -- best-effort UI cleanup
            pass


async def _resource_page(
    contexts: list[BrowserContext], resource: str
) -> tuple[Page | None, bool]:
    expected_paths = _PAGE_PATHS[resource]
    for context in contexts:
        page = None
        try:
            page = await context.new_page()
            page_url = _resource_url([context], resource)
            await page.goto(
                page_url,
                wait_until="domcontentloaded",
                timeout=PAGE_NAVIGATION_TIMEOUT_MS,
            )
            if any(matches_page(page, path) for path in expected_paths):
                return page, True
        except Exception:  # noqa: BLE001,S110 -- try the next browser context
            pass
        if page is not None:
            await _close_page(page)
    return None, False


def _resource_url(contexts: list[BrowserContext], resource: str) -> str:
    for context in contexts:
        for page in context.pages:
            split = urlsplit(page.url)
            if not is_affiliate_host(split.hostname):
                continue
            query = parse_qs(split.query)
            shop_id = query.get("shop_id", [None])[0]
            if not shop_id:
                continue
            values = {"shop_id": shop_id}
            shop_region = query.get("shop_region", [None])[0]
            if shop_region:
                values["shop_region"] = shop_region
            path = urlsplit(_PAGE_URL[resource]).path
            return f"{split.scheme}://{split.netloc}{path}?{urlencode(values)}"
    return _PAGE_URL[resource]


async def _close_page(page: Page) -> None:
    try:
        await asyncio.wait_for(page.close(), timeout=PAGE_CLOSE_TIMEOUT_SECONDS)
    except Exception:  # noqa: BLE001,S110 -- detached pages are already harmless
        pass


def _video_range_end(value: str) -> date | None:
    parts = re.split(r"\s*-\s*", value.strip())
    if len(parts) != 2:
        return None
    part = parts[1].strip()
    for pattern, order in (
        (r"(\d{4})/(\d{1,2})/(\d{1,2})", (1, 2, 3)),
        (r"(\d{1,2})/(\d{1,2})/(\d{4})", (3, 1, 2)),
    ):
        match = re.fullmatch(pattern, part)
        if match:
            values = [int(match.group(index)) for index in order]
            return date(*values)
    return None
