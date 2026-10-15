"""Read fresh video export availability without touching existing browser pages."""

from __future__ import annotations

import asyncio
from datetime import date
from urllib.parse import parse_qs, urlsplit

from playwright.async_api import BrowserContext, Page

from backend.app.services.tiktok_affiliate_analytics_page_control import (
    is_affiliate_host,
    matches_page,
    page_security_failure,
)

VIDEO_EXPORT_PATH = "/affiliate/assets/video-analysis"
EXPORT_PICKER_TIMEOUT_SECONDS = 12.0


async def detect_video_export_picker_day(
    context: BrowserContext, page_url: str, detect_page_date
) -> date | None:
    expected = urlsplit(page_url)
    shop_ids = parse_qs(expected.query).get("shop_id", [])
    if not is_affiliate_host(expected.hostname) or len(shop_ids) != 1 or not shop_ids[0]:
        return None
    export_url = expected._replace(path=VIDEO_EXPORT_PATH).geturl()
    page: Page | None = None

    def matches_identity() -> bool:
        if page is None:
            return False
        observed = urlsplit(page.url)
        return (
            observed.scheme == expected.scheme
            and observed.netloc == expected.netloc
            and parse_qs(observed.query).get("shop_id", []) == shop_ids
            and matches_page(page, VIDEO_EXPORT_PATH)
        )

    async def probe() -> date | None:
        nonlocal page
        page = await context.new_page()
        await page.goto(export_url, wait_until="domcontentloaded", timeout=8_000)
        if not matches_identity() or await page_security_failure(page) is not None:
            return None
        latest = await detect_page_date(page, "videos", refresh=False)
        if not matches_identity() or await page_security_failure(page) is not None:
            return None
        return latest

    try:
        return await asyncio.wait_for(probe(), timeout=EXPORT_PICKER_TIMEOUT_SECONDS)
    except Exception:  # noqa: BLE001 -- caller retains conservative API fallback
        return None
    finally:
        if page is not None:
            try:
                await asyncio.wait_for(page.close(), timeout=2)
            except Exception:  # noqa: BLE001,S110 -- only our temporary page
                pass
