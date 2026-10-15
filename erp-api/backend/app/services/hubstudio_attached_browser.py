from __future__ import annotations

import asyncio
from collections.abc import Callable

from playwright.async_api import Browser, BrowserContext, Playwright


class AttachedHubstudioBrowser:
    """Limited view of an externally owned HubStudio browser."""

    def __init__(self, browser: Browser) -> None:
        self._browser = browser

    @property
    def contexts(self) -> list[BrowserContext]:
        return self._browser.contexts

    def on(self, event: str, callback: Callable[..., None]) -> None:
        self._browser.on(event, callback)


async def connect_attached_hubstudio_browser(
    playwright: Playwright,
    cdp_url: str,
    *,
    timeout_seconds: float = 60.0,
) -> AttachedHubstudioBrowser:
    if timeout_seconds <= 0:
        raise ValueError("HubStudio CDP timeout must be positive.")
    browser = await asyncio.wait_for(
        playwright.chromium.connect_over_cdp(cdp_url),
        timeout=timeout_seconds,
    )
    return AttachedHubstudioBrowser(browser)
