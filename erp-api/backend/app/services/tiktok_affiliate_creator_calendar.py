from __future__ import annotations

import asyncio
import re
from datetime import date

from playwright.async_api import Page

from backend.app.services.tiktok_affiliate_intent_types import IntentPageError

_CREATOR_TRIGGER = ".m4b-date-picker-range-trigger"
_MAX_MONTH_STEPS = 36


def _month_index(value: str) -> int:
    match = re.fullmatch(r"(\d{4})-(\d{2})", value.strip())
    if match is None:
        raise IntentPageError("window_not_settable")
    return int(match.group(1)) * 12 + int(match.group(2))


def navigation_step(headers: tuple[str, str], target: date) -> int:
    left, right = (_month_index(value) for value in headers)
    wanted = target.year * 12 + target.month
    if left <= wanted <= right:
        return 0
    if abs(wanted - left) > _MAX_MONTH_STEPS:
        raise IntentPageError("window_not_settable")
    return -1 if wanted < left else 1


async def select_creator_date(page: Page, value: date) -> None:
    trigger = page.locator(_CREATOR_TRIGGER)
    await trigger.wait_for(state="visible", timeout=30_000)
    headers = trigger.locator(".arco-picker-header-value")
    await headers.nth(0).wait_for(state="visible", timeout=30_000)
    if await headers.count() < 2:
        raise IntentPageError("window_not_settable")
    icons = trigger.locator(
        ".arco-picker-header-icon:not(.arco-picker-header-icon-hidden)"
    )
    for _ in range(_MAX_MONTH_STEPS + 1):
        visible = (
            (await headers.nth(0).inner_text()).strip(),
            (await headers.nth(1).inner_text()).strip(),
        )
        step = navigation_step(visible, value)
        if step == 0:
            break
        await icons.nth(1 if step < 0 else 2).evaluate(
            "(element) => element.click()"
        )
        await asyncio.sleep(0.1)
    else:
        raise IntentPageError("window_not_settable")
    panels = trigger.locator(".arco-panel-date-inner")
    target_header = f"{value.year:04d}-{value.month:02d}"
    for index in range(await panels.count()):
        panel = panels.nth(index)
        if (
            await panel.locator(".arco-picker-header-value").inner_text()
        ).strip() != target_header:
            continue
        cells = panel.locator(".arco-picker-cell-in-view:not(.arco-picker-cell-disabled)")
        for cell_index in range(await cells.count()):
            cell = cells.nth(cell_index)
            if (await cell.inner_text()).strip() == str(value.day):
                await cell.hover()
                await cell.click()
                return
    raise IntentPageError("window_not_settable")
