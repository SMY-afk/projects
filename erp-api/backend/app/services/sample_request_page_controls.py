from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Mapping
from urllib.parse import urlsplit

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

_REVIEW_TAB = re.compile(r"^(?:To review|待审核)(?:\s|$)", re.IGNORECASE)
_REQUEST_DATE = re.compile(
    r"^(?:Request date|Application date|申请日期)$", re.IGNORECASE
)
_RELEVANCY = re.compile(r"^(?:Relevancy|Relevance|相关性)$", re.IGNORECASE)
_SORT_VALUE = ".core-select-view-value"
_NEXT_PAGE = "li.core-pagination-item-next:not(.core-pagination-item-disabled)"
_SAMPLE_LIST_PATH = "/api/v1/affiliate/sample/group/list"


async def select_free_sample_tab(page: Page) -> None:
    tab = page.get_by_role(
        "tab", name=re.compile(r"^(?:Free samples?|免费样品)$", re.IGNORECASE)
    ).filter(visible=True)
    for _ in range(40):
        count = await tab.count()
        if count <= 1:
            try:
                await tab.wait_for(state="visible", timeout=30_000)
                break
            except PlaywrightError as error:
                if "strict mode violation" not in str(error).casefold():
                    raise
        # React may briefly render both old and replacement tab headers.
        # Never click either candidate until there is exactly one visible tab.
        await asyncio.sleep(0.1)
    else:
        raise RuntimeError("sample_free_tab_unavailable")
    for _ in range(40):
        state = await _free_tab_selected(tab)
        if state is True:
            return
        if state is False:
            try:
                await tab.click(timeout=30_000, no_wait_after=True)
                break
            except PlaywrightError as error:
                if "strict mode violation" not in str(error).casefold():
                    raise
        await asyncio.sleep(0.1)
    else:
        raise RuntimeError("sample_free_tab_unavailable")
    for _ in range(40):
        if await _free_tab_selected(tab) is True:
            return
        await asyncio.sleep(0.1)
    raise RuntimeError("sample_free_tab_not_selected")


async def _free_tab_selected(tab) -> bool | None:
    if await tab.count() != 1:
        return None
    try:
        return await tab.get_attribute("aria-selected") == "true"
    except PlaywrightError as error:
        if "strict mode violation" not in str(error).casefold():
            raise
        return None


async def prepare_sample_review_page(page: Page, *, select_free=False) -> None:
    """Select the review queue and newest-request ordering before capture."""
    if select_free:
        await select_free_sample_tab(page)
    await _select_review_status(page)
    await _select_request_date(page)


async def next_sample_page(page: Page) -> bool:
    locator = page.locator(_NEXT_PAGE)
    if await locator.count() != 1:
        return False
    await locator.click(no_wait_after=True)
    return True


async def _select_review_status(page: Page) -> None:
    locator = page.get_by_role("tab", name=_REVIEW_TAB).filter(visible=True)
    if await locator.get_attribute("aria-selected") != "true":
        for attempt in range(2):
            try:
                await locator.click(timeout=30_000, force=True, no_wait_after=True)
                break
            except PlaywrightTimeoutError:
                if attempt == 1:
                    raise
        await page.wait_for_timeout(1_500)
    await _wait_for_sort(page, attempts=120)
    if await locator.get_attribute("aria-selected") != "true":
        raise RuntimeError("sample_review_tab_not_selected")


async def _select_request_date(page: Page, *, attempts: int = 120) -> None:
    state, locator = await _wait_for_sort(page, attempts=attempts)
    if state == "relevance":
        await _choose_sort(
            page,
            locator,
            _REQUEST_DATE,
            [],
        )
    await _wait_for_sort(page, expected="date", attempts=attempts)
    await page.wait_for_timeout(1_000)
    if (await _sort_state(page))[0] != "date":
        raise RuntimeError("sample_request_date_sort_unstable")


async def _sort_state(page: Page):
    values = page.locator(_SORT_VALUE).filter(visible=True)
    candidates = []
    for index in range(await values.count()):
        candidate = values.nth(index)
        text = (await candidate.inner_text()).strip()
        if _REQUEST_DATE.fullmatch(text):
            candidates.append(("date", candidate))
        elif _RELEVANCY.fullmatch(text):
            candidates.append(("relevance", candidate))
    # React can briefly retain both old and replacement controls. Selecting the
    # first match could act on a stale panel, so wait until the control is unique.
    return candidates[0] if len(candidates) == 1 else (None, None)


async def _wait_for_sort(page: Page, *, attempts: int, expected: str | None = None):
    for attempt in range(attempts):
        state, locator = await _sort_state(page)
        if locator is not None and (expected is None or state == expected):
            return state, locator
        if attempt + 1 < attempts:
            await asyncio.sleep(0.25)
    raise RuntimeError("sample_request_date_sort_unavailable")


async def _choose_sort(page: Page, locator, option_name, order_params: list) -> None:
    for attempt in range(3):
        await locator.click(timeout=30_000, no_wait_after=True)
        option = page.get_by_role("option", name=option_name).filter(visible=True)
        try:
            async with page.expect_response(
                lambda response: _matches_sort_response(response, order_params),
                timeout=5_000,
            ) as pending:
                await option.click(timeout=10_000, no_wait_after=True)
            await pending.value
            return
        except PlaywrightTimeoutError:
            if (await _sort_state(page))[0] == "date":
                return
            if attempt == 2:
                raise


def _matches_sort_response(response, order_params: list) -> bool:
    split = urlsplit(response.url)
    if split.path != _SAMPLE_LIST_PATH or response.request.method != "POST":
        return False
    try:
        payload = json.loads(response.request.post_data or "")
    except (TypeError, ValueError, UnicodeDecodeError):
        return False
    if not isinstance(payload, Mapping):
        return False
    search = payload.get("search_params", [])
    return (
        payload.get("tab") == 10
        and payload.get("order_params") == order_params
        and isinstance(search, list)
        and all(
            isinstance(item, Mapping) and item.get("value") in (None, "")
            for item in search
        )
    )
