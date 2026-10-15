"""Capture complete free-review RAW through the verified running Ziniao browser."""

import asyncio
import json
import platform
from pathlib import Path

from playwright.async_api import async_playwright

from backend.app.services.hubstudio_raw_sample_capture import (
    capture_review_batch_from_page,
)
from backend.app.services.sample_raw_batch_store import SampleRawBatchStore
from backend.app.services.sample_raw_capture_retry import recover_fresh_completed
from backend.app.services.sample_raw_owned_page import open_owned_sample_page
from backend.app.services.sample_request_page_controls import select_free_sample_tab
from scripts.local_capture_guard import browser_work, ensure_browser_ready
from scripts.run_local_affiliate_heartbeat import ZINIAO_PLATFORM_SHOP_ID
from scripts.ziniao_affiliate_export_source import resolve_ziniao_export_source

ROOT = Path(".runtime/local-official-filter-build")
SHOP_ID = "6fdc5cdc-90da-5524-82f7-9b11746c5e10"


async def main():
    with browser_work("local"):
        endpoint, _environment = await resolve_ziniao_export_source(
            ZINIAO_PLATFORM_SHOP_ID
        )
        await ensure_browser_ready("local", endpoint)
        store = SampleRawBatchStore(ROOT / "raw", SHOP_ID)
        await asyncio.to_thread(recover_fresh_completed, store)
        async with (
            async_playwright() as playwright,
            open_owned_sample_page(
                playwright,
                endpoint,
                ZINIAO_PLATFORM_SHOP_ID,
                host="affiliate-us.tiktok.com",
            ) as (page, url),
        ):
            await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
            await select_free_sample_tab(page)
            capture = await capture_review_batch_from_page(
                page,
                ZINIAO_PLATFORM_SHOP_ID,
                store,
                timeout_seconds=60,
            )
        rows = store.load_pages(capture.batch)
        result = {
            "shop_id": SHOP_ID,
            "platform_shop_id": ZINIAO_PLATFORM_SHOP_ID,
            "observed_at": min(row.response_observed_at for row in rows).isoformat(),
            "page_count": capture.batch.page_count,
            "expected_total": capture.batch.expected_total,
            "captured_total": capture.batch.captured_total,
            "request_id": rows[-1].request_id,
            "applications": [
                item for page in capture.pages for item in page.applications
            ],
        }
        path = ROOT / "ziniao-review.json"
        path.write_text(
            json.dumps(result, ensure_ascii=False, default=str), encoding="utf-8"
        )
        print(
            json.dumps(
                {
                    key: result[key]
                    for key in (
                        "shop_id",
                        "observed_at",
                        "page_count",
                        "expected_total",
                        "captured_total",
                    )
                }
            ),
            flush=True,
        )
        print(f"CAPTURE_FILE={path.resolve()}", flush=True)


if __name__ == "__main__":
    platform._wmi = None
    asyncio.run(asyncio.wait_for(main(), timeout=240))
