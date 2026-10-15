"""Inspect one HubStudio shop's sample tab and sort state without mutations."""

from __future__ import annotations

import argparse
import asyncio
from urllib.parse import parse_qs, urlsplit

from playwright.async_api import async_playwright

from backend.app.services.hubstudio_attached_browser import (
    connect_attached_hubstudio_browser,
)
from backend.app.services.hubstudio_cdp import discover_hubstudio_cdp_url
from scripts.run_remote_sample_capture_loop import SHOPS


async def main(label: str) -> None:
    _shop_id, _environment_id, platform_shop_id = SHOPS[label]
    cdp_url = await discover_hubstudio_cdp_url(
        current_url=None, expected_platform_shop_id=platform_shop_id
    )
    if cdp_url is None:
        raise RuntimeError("Exact-shop CDP is unavailable")
    async with async_playwright() as playwright:
        browser = await connect_attached_hubstudio_browser(
            playwright, cdp_url, timeout_seconds=15
        )
        matching = [
            page
            for context in browser.contexts
            for page in context.pages
            if urlsplit(page.url).path == "/affiliate/sample/sample-request"
            and parse_qs(urlsplit(page.url).query).get("shop_id")
            == [platform_shop_id]
        ]
        print(f"SHOP={label} MATCHING_SAMPLE_PAGES={len(matching)}")
        for index, page in enumerate(matching, 1):
            try:
                tabs = page.get_by_role("tab", name="To review").filter(visible=True)
                tab_count = await asyncio.wait_for(tabs.count(), 10)
                selected = (
                    await asyncio.wait_for(tabs.first.get_attribute("aria-selected"), 10)
                    if tab_count else None
                )
                sorts = page.locator(".core-select-view-value")
                sort_values = [
                    (await asyncio.wait_for(sorts.nth(i).inner_text(), 10)).strip()
                    for i in range(min(await asyncio.wait_for(sorts.count(), 10), 5))
                ]
                print(
                    f"PAGE={index} REVIEW_TABS={tab_count} "
                    f"SELECTED={selected} SORT_VALUES={sort_values}"
                )
            except Exception as error:  # noqa: BLE001 -- read-only CDP diagnostics
                print(f"PAGE={index} READ_ERROR={type(error).__name__}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shop-label", choices=SHOPS, required=True)
    args = parser.parse_args()
    asyncio.run(main(args.shop_label))
