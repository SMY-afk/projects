"""Read the real creator-details link from one owned refundable page."""

import asyncio
import json
import re
from urllib.parse import parse_qs, urlsplit

from playwright.async_api import async_playwright

from backend.app.services.hubstudio_cdp import discover_hubstudio_cdp_url
from backend.app.services.sample_raw_owned_page import open_owned_sample_page
from erp_api.services.refundable_sample_parser import REFUNDABLE_PATH
from scripts.run_remote_sample_capture_loop import SHOPS


async def run():
    _, _, shop = SHOPS["cross-border-12"]
    endpoint = await discover_hubstudio_cdp_url(current_url=None, expected_platform_shop_id=shop)
    async with async_playwright() as playwright, open_owned_sample_page(playwright, endpoint, shop) as (page, url):
        await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        paid = page.get_by_text(re.compile(r"^(?:Refundable samples?|买返样品)$", re.IGNORECASE)).filter(visible=True)
        await paid.wait_for(state="visible", timeout=60_000)
        async with page.expect_response(lambda response: urlsplit(response.url).path == REFUNDABLE_PATH, timeout=60_000):
            await paid.click(timeout=30_000)
        creator = page.get_by_text("@brayduece1", exact=True)
        await creator.wait_for(state="visible", timeout=30_000)
        details = await creator.evaluate("element => ({tag:element.tagName,href:element.closest('a')?.href,html:element.outerHTML})")
        href = details.get("href")
        if href:
            split = urlsplit(href)
            details["href"] = {"path": split.path, "query": {key: value for key, value in parse_qs(split.query).items() if key in {'cname','cid','creator_id','shop_id','shop_region'}}}
        print(json.dumps(details, ensure_ascii=True))
        await page.evaluate("""window.open = (url) => {
            window.erpProbeUrl = url;
            const location = {set href(value){window.erpProbeUrl=String(value);},get href(){return window.erpProbeUrl;}};
            return {focus(){},get location(){return location;},set location(value){window.erpProbeUrl=String(value);}};
        }""")
        await creator.click(timeout=15_000)
        await page.wait_for_timeout(1_000)
        opened = await page.evaluate("window.erpProbeUrl || window.location.href")
        split = urlsplit(opened)
        print(json.dumps({"opened_path": split.path, "query_keys": list(parse_qs(split.query)),
                          "query": {key: value for key, value in parse_qs(split.query).items() if key in {'cname','cid','creator_id','creator_oec_id','shop_id','shop_region'}}}, ensure_ascii=True))


if __name__ == "__main__":
    asyncio.run(run())
