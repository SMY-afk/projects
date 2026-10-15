"""Handle cached paid panels without repeated page reloads or blind clicks."""

import asyncio
import re

from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from backend.app.services.tiktok_affiliate_analytics_page_control import (
    page_security_failure,
)

ACTIVE_LABELS = {
    1: r"^(?:Ready to Ship|待发货)",
    2: r"^(?:Shipped|已发货)",
    3: r"^(?:In[- ]progress|处理中)",
}


async def select_paid_panel(page, response_matches):
    tab = page.get_by_role("tab", name=re.compile(
        r"^(?:买返样品|Refundable samples?)$", re.IGNORECASE
    )).filter(visible=True)
    await tab.wait_for(state="visible", timeout=30_000)
    if await tab.count() != 1:
        raise RuntimeError("Refundable sample type tab is ambiguous")
    if failure := await page_security_failure(page):
        raise RuntimeError(failure[1])
    try:
        async with page.expect_response(response_matches, timeout=5_000) as selected:
            await tab.click(timeout=15_000, no_wait_after=True)
        return await selected.value
    except PlaywrightTimeoutError:
        if failure := await page_security_failure(page):
            raise RuntimeError(failure[1])
        if await tab.get_attribute("aria-selected") != "true":
            raise
        # A correctly selected cached panel need not send a list request.
        return None


async def reset_selected_status(panel, status, tab_type):
    if await status.get_attribute("aria-selected") != "true":
        return
    alternate = 2 if tab_type == 1 else 1
    tab = panel.get_by_role("tab", name=re.compile(
        ACTIVE_LABELS[alternate], re.IGNORECASE
    )).filter(visible=True)
    if await tab.count() != 1:
        raise RuntimeError("Refundable refresh status is missing or ambiguous")
    await tab.click(timeout=15_000, no_wait_after=True)
    for _ in range(40):
        if await status.get_attribute("aria-selected") != "true":
            return
        await asyncio.sleep(0.1)
    raise RuntimeError("Refundable cached status did not release selection")
