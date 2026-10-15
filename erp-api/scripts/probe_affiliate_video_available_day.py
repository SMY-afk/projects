"""Read the latest selectable affiliate video day in one verified CDP shop."""

from __future__ import annotations

import argparse
import asyncio
from urllib.parse import parse_qs, urlsplit

from playwright.async_api import async_playwright

from backend.app.services.hubstudio_attached_browser import (
    connect_attached_hubstudio_browser,
)
from backend.app.services.tiktok_affiliate_available_date import _detect_page_date
from backend.app.services.tiktok_affiliate_video_available_date import (
    detect_video_api_latest_day,
)


async def probe(cdp_url: str, platform_shop_id: str) -> None:
    async with async_playwright() as playwright:
        browser = await connect_attached_hubstudio_browser(playwright, cdp_url)
        matching_contexts = [
            context
            for context in browser.contexts
            if any(
                platform_shop_id
                in parse_qs(urlsplit(page.url).query).get("shop_id", [])
                for page in context.pages
            )
        ]
        if len(matching_contexts) != 1:
            raise RuntimeError("Expected shop was not found in exactly one CDP context.")
        page = await matching_contexts[0].new_page()
        try:
            await page.goto(
                "https://affiliate.tiktokshopglobalselling.com/insights/"
                f"video-analysis?shop_id={platform_shop_id}",
                wait_until="domcontentloaded",
                timeout=15_000,
            )
            await asyncio.sleep(2)
            if platform_shop_id not in parse_qs(urlsplit(page.url).query).get(
                "shop_id", []
            ):
                raise RuntimeError("Video page did not retain the expected shop ID.")
            print(f"page_path={urlsplit(page.url).path}")
            print(f"current_picker_count={await page.locator('.pulse-date-picker-range').count()}")
            latest = await _detect_page_date(page, "videos")
            print(f"latest_selectable_video_day={latest.isoformat() if latest else 'unknown'}")
            api_latest = await detect_video_api_latest_day(matching_contexts[0], page.url)
            print(
                "latest_api_video_day="
                f"{api_latest.isoformat() if api_latest else 'unknown'}"
            )
        finally:
            await page.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cdp-url", required=True)
    parser.add_argument("--platform-shop-id", required=True)
    args = parser.parse_args()
    asyncio.run(probe(args.cdp_url, args.platform_shop_id))


if __name__ == "__main__":
    main()
