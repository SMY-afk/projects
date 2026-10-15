"""Refresh approved, already-loaded cross3/cross7 review pages without reloads."""
import asyncio
import re

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from backend.app.services.hubstudio_sample_watch import _sample_page_matches
from backend.app.services.sample_request_page_controls import (
    _RELEVANCY,
    _select_request_date,
    _wait_for_sort,
    prepare_sample_review_page,
)


async def reset_date_sort(page):
    _state, locator = await _wait_for_sort(page, expected="date", attempts=120)
    await locator.click(timeout=15_000, no_wait_after=True)
    option = page.get_by_role("option", name=_RELEVANCY).filter(visible=True)
    if await option.count() != 1:
        raise RuntimeError("sample_refresh_sort_ambiguous")
    await option.click(timeout=15_000, no_wait_after=True)
    await _wait_for_sort(page, expected="relevance", attempts=120)


async def reset_first_review_page(page):
    first = page.locator("li.core-pagination-item").filter(has_text=re.compile(r"^1$")).filter(visible=True)
    active = page.locator("li.core-pagination-item-active").filter(visible=True)
    first_count, active_count = await first.count(), await active.count()
    if first_count == active_count == 0:
        return  # An empty queue can have no pager; its RAW request must still prove page 1.
    if first_count != 1 or active_count != 1:
        raise RuntimeError("sample_review_first_page_ambiguous")
    if await first.get_attribute("aria-current") != "true":
        await first.click(timeout=15_000, no_wait_after=True)
    for _ in range(40):
        if await first.count() == 1 and await first.get_attribute("aria-current") == "true":
            return
        await asyncio.sleep(0.1)
    raise RuntimeError("sample_review_first_page_not_selected")


async def prepare_reused_review(page, platform_shop_id, initial_url):
    if (platform_shop_id not in {"9622543325839925006", "9121478993551097445"}
            or initial_url is not None
            or not _sample_page_matches(page.url, platform_shop_id)):
        return False
    # Preparatory responses are not part of the new capture. The collector
    # subscribes afterward and fences responses by their request object.
    await prepare_sample_review_page(page, select_free=True)
    await reset_date_sort(page)
    await reset_first_review_page(page)
    return True


async def trigger_review_refresh(page):
    # This uses the existing tab=10, empty-filter, request-date response matcher.
    await _select_request_date(page)


async def _load_first_page(page, platform_shop_id, initial_url):
    try:
        if initial_url is not None:
            await page.goto(initial_url, wait_until="domcontentloaded", timeout=30_000)
        else:
            await page.reload(wait_until="commit", timeout=5_000)
    except PlaywrightTimeoutError:
        if not _sample_page_matches(page.url, platform_shop_id):
            raise
    except PlaywrightError as error:
        if "net::ERR_ABORTED" not in str(error) or not _sample_page_matches(page.url, platform_shop_id):
            raise
    await prepare_sample_review_page(page, select_free=True)
