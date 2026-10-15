from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

from playwright.async_api import BrowserContext

from backend.app.services.tiktok_affiliate_analytics_page_control import (
    page_security_failure,
)

AVAILABLE_DATE_PATH = "/api/v1/oec/affiliate/compass/available_date/get"
VIDEO_MODULE_TYPES = frozenset(
    {101, 103, 104, 107, 108, 203, 205, 206, 301, 302, 601, 602}
)


async def detect_video_api_latest_day(
    context: BrowserContext, page_url: str
) -> date | None:
    expected_shop_ids = parse_qs(urlsplit(page_url).query).get("shop_id", [])
    if len(expected_shop_ids) != 1:
        return None
    page = await context.new_page()
    try:
        async with page.expect_response(
            lambda response: (
                urlsplit(response.url).path == AVAILABLE_DATE_PATH
                and response.request.method.upper() == "POST"
            ),
            timeout=20_000,
        ) as response_event:
            await page.goto(page_url, wait_until="domcontentloaded", timeout=15_000)
        response = await response_event.value
        if response.status != 200 or await page_security_failure(page) is not None:
            return None
        observed_shop_ids = parse_qs(urlsplit(page.url).query).get("shop_id", [])
        if observed_shop_ids != expected_shop_ids:
            return None
        return video_day_from_available_ranges(
            response.request.post_data_json, await response.json()
        )
    except Exception:  # noqa: BLE001 -- unavailable TikTok evidence fails closed
        return None
    finally:
        try:
            await asyncio.wait_for(page.close(), timeout=2)
        except Exception:  # noqa: BLE001,S110 -- close only our temporary tab
            pass


def video_day_from_available_ranges(request: object, payload: object) -> date | None:
    if not isinstance(request, dict) or not isinstance(payload, dict):
        return None
    requested = request.get("module_types")
    data = payload.get("data")
    rows = data.get("available_time_range_list") if isinstance(data, dict) else None
    if (
        payload.get("code") != 0
        or not isinstance(requested, list)
        or not requested
        or not isinstance(rows, list)
        or len(rows) != len(requested)
        or any(type(value) is not int for value in requested)
        or set(requested) != VIDEO_MODULE_TYPES
    ):
        return None
    by_module = {}
    for row in rows:
        if not isinstance(row, dict):
            return None
        module = row.get("module_type")
        start = row.get("start_time")
        end = row.get("end_time")
        offset = row.get("timezone_offset")
        if (
            type(module) is not int
            or type(start) is not int
            or type(end) is not int
            or type(offset) is not int
            or end <= start
            or module in by_module
        ):
            return None
        by_module[module] = row
    if set(by_module) != set(requested):
        return None
    latest_common = min(rows, key=lambda row: row["end_time"])
    if max(row["start_time"] for row in rows) >= latest_common["end_time"]:
        return None
    try:
        zone = timezone(timedelta(seconds=latest_common["timezone_offset"]))
        # TikTok's end_time is exclusive; the export picker ends the day before.
        return (
            datetime.fromtimestamp(latest_common["end_time"] - 1, UTC)
            .astimezone(zone)
            .date()
        )
    except (OverflowError, ValueError):
        return None
