from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable

from playwright.async_api import Page

from backend.app.services.tiktok_affiliate_analytics_page_control import (
    RESOURCE_PAGE,
    capture_log,
    matches_page,
    page_security_failure,
)

FailureHandler = Callable[[Page | None, str, str, str], Awaitable[None]]
AUTO_START_NAVIGATION_TIMEOUT_SECONDS = 30.0


async def auto_start_open_pages_once(
    pages: Iterable[Page],
    *,
    mutation_lock: asyncio.Lock,
    started_resources: set[str],
    failure_handler: FailureHandler,
) -> None:
    """Reload at most one existing target page for each daemon resource."""
    open_pages = tuple(pages)
    for resource, (page_path, _) in RESOURCE_PAGE.items():
        if resource in started_resources:
            continue
        page = next(
            (
                candidate
                for candidate in open_pages
                if matches_page(candidate, page_path)
            ),
            None,
        )
        if page is None:
            continue

        started_resources.add(resource)
        security_failure = await page_security_failure(page)
        if security_failure is not None:
            async with mutation_lock:
                await failure_handler(page, resource, *security_failure)
            continue
        try:
            await asyncio.wait_for(
                page.reload(wait_until="domcontentloaded"),
                timeout=AUTO_START_NAVIGATION_TIMEOUT_SECONDS,
            )
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 -- browser boundary
            async with mutation_lock:
                await failure_handler(
                    page,
                    resource,
                    "failed",
                    "auto_start_failed",
                )
            capture_log(
                "affiliate_analytics_auto_start_failed",
            )
            continue
        capture_log("affiliate_analytics_auto_start_requested")
