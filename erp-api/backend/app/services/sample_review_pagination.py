from __future__ import annotations

import asyncio

from playwright.async_api import Page

from backend.app.services.sample_request_page_controls import next_sample_page


async def capture_all_review_pages(
    page: Page,
    completed: asyncio.Event,
    listener,
    *,
    timeout_seconds: float,
) -> int:
    """Wait for and process every page in the selected review queue."""
    pages = 0
    while True:
        await asyncio.wait_for(completed.wait(), timeout=timeout_seconds)
        await listener.wait_for_pending()
        pages += 1
        completed.clear()
        if not await next_sample_page(page):
            return pages
