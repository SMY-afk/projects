"""Read current creator/video source dates in verified Ziniao CDP."""

import asyncio
import json
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

from playwright.async_api import async_playwright

from backend.app.services.hubstudio_attached_browser import (
    connect_attached_hubstudio_browser,
)
from backend.app.services.tiktok_affiliate_scheduled_creator_page import (
    close_owned_page,
)
from scripts.probe_daily_valid_creator_online import detect_required_dates
from scripts.ziniao_affiliate_export_source import resolve_ziniao_export_source

SHOP_ID = "9136806951995371293"


async def probe() -> dict[str, str]:
    cdp_url, _environment_id = await resolve_ziniao_export_source(SHOP_ID)
    async with async_playwright() as playwright:
        browser = await connect_attached_hubstudio_browser(playwright, cdp_url)
        contexts = [
            context
            for context in browser.contexts
            if any(
                parse_qs(urlsplit(page.url).query).get("shop_id") == [SHOP_ID]
                for page in context.pages
            )
        ]
        if len(contexts) != 1:
            raise RuntimeError("Ziniao shop context is missing or ambiguous")
        context = contexts[0]
        owned = await context.new_page()
        try:
            await owned.goto(
                "https://affiliate-us.tiktok.com/data/creator-analysis"
                f"?shop_region=US&shop_id={SHOP_ID}",
                wait_until="domcontentloaded",
                timeout=30_000,
            )
            if parse_qs(urlsplit(owned.url).query).get("shop_id") != [SHOP_ID]:
                raise RuntimeError("Ziniao creator tab changed shop identity")
            dates = await detect_required_dates([context])
        finally:
            await close_owned_page(owned)
    if set(dates) != {"creators", "videos"}:
        raise RuntimeError("Ziniao creator/video dates are not independently verified")
    return {
        "shop": "本土店",
        "observed_at": datetime.now(UTC).isoformat(),
        **{key: value.isoformat() for key, value in dates.items()},
    }


async def main() -> None:
    print(json.dumps(await probe(), ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
