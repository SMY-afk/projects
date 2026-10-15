"""Inspect refundable sample contracts in an isolated, exact-shop scratch page."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from playwright.async_api import async_playwright

from backend.app.services.hubstudio_cdp import discover_hubstudio_cdp_url
from backend.app.services.hubstudio_cdp_ownership import assert_erp_hubstudio_cdp_url
from backend.app.services.sample_raw_owned_page import open_owned_sample_page
from erp_api.services.affiliate_center_capture_policy import sanitize_capture_payload
from scripts.run_remote_sample_capture_loop import SHOPS

REFUNDABLE_TAB = re.compile(r"^(?:买返样品|Refundable samples?)$", re.IGNORECASE)
SAFE_REQUEST_KEYS = {
    "tab", "page", "page_size", "page_num", "cursor", "order_params",
    "search_params", "sample_type", "sample_order_type", "request_type",
    "refund_type", "sample_mode", "type", "status", "is_refundable",
    "tab_type", "cur_page", "search_param",
}


async def run(label: str, directory: Path) -> None:
    shop_id, _, platform_shop_id = SHOPS[label]
    endpoint = await discover_hubstudio_cdp_url(
        current_url=None, expected_platform_shop_id=platform_shop_id
    )
    if endpoint is None:
        raise RuntimeError("Exact-shop browser is unavailable")
    assert_erp_hubstudio_cdp_url(endpoint)
    directory = directory / shop_id
    directory.mkdir(parents=True, exist_ok=True)
    captured = []
    tasks = set()

    async def read(response):
        split = urlsplit(response.url)
        if "/sample/" not in split.path or response.request.method != "POST":
            return
        try:
            request = json.loads(response.request.post_data or "{}")
            payload = await response.json()
        except (ValueError, UnicodeDecodeError):
            return
        row = {
            "path": split.path,
            "http_status": response.status,
            "request_keys": sorted(request),
            "request": {key: request[key] for key in SAFE_REQUEST_KEYS & request.keys()},
            "payload": sanitize_capture_payload(payload),
            "observed_at": datetime.now(UTC).isoformat(),
        }
        captured.append(row)

    def schedule(response):
        task = asyncio.create_task(read(response))
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    async with async_playwright() as playwright, open_owned_sample_page(
        playwright, endpoint, platform_shop_id
    ) as (page, url):
        page.on("response", schedule)
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            paid = page.get_by_text(REFUNDABLE_TAB, exact=True).filter(visible=True)
            await paid.wait_for(state="visible", timeout=60_000)
            await page.wait_for_timeout(3_000)
            free_count = len(captured)
            for attempt in range(3):
                try:
                    async with page.expect_response(
                        lambda response: urlsplit(response.url).path
                        == "/api/v1/affiliate/sample/refundable/apply/list",
                        timeout=20_000,
                    ) as pending:
                        await paid.click(timeout=15_000)
                    await pending.value
                    break
                except TimeoutError:
                    if attempt == 2:
                        raise
            await page.wait_for_timeout(2_000)
            print("REFUNDABLE_PAGE_TEXT=" + json.dumps(
                (await page.locator("body").inner_text())[:7000], ensure_ascii=True
            ))
            print("FREE_RESPONSE_COUNT=" + str(free_count))
            for label_pattern in (
                r"^(?:Ready to Ship|待发货)", r"^(?:Shipped|已发货)",
                r"^(?:In-progress|处理中)", r"^(?:Refunded|已返款)",
                r"^(?:Not refunded|未返款)", r"^(?:Cancelled|已取消)",
            ):
                tab = page.get_by_role("tab", name=re.compile(label_pattern, re.IGNORECASE))
                tab = tab.filter(visible=True)
                if await tab.count() != 1:
                    raise RuntimeError("Refundable status tab is ambiguous")
                await tab.click(timeout=15_000)
                await page.wait_for_timeout(2_000)
        finally:
            page.remove_listener("response", schedule)
            if tasks:
                await asyncio.gather(*tuple(tasks), return_exceptions=True)
    (directory / "contract.json").write_text(
        json.dumps(captured, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({
        "shop": label,
        "responses": [{key: row[key] for key in (
            "path", "http_status", "request_keys", "request"
        )} for row in captured],
    }, ensure_ascii=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shop-label", choices=SHOPS, required=True)
    parser.add_argument("--output", type=Path, default=Path(".runtime/refundable-contract"))
    args = parser.parse_args()
    asyncio.run(run(args.shop_label, args.output))
