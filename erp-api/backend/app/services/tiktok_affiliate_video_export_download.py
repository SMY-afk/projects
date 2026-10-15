from __future__ import annotations

import asyncio
import re
import tempfile
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

from playwright.async_api import Download, Locator, Page, Response

from backend.app.services.tiktok_affiliate_analytics_page_control import (
    capture_log,
    is_affiliate_host,
)
from backend.app.services.tiktok_affiliate_video_export_calendar import _select_date
from backend.app.services.tiktok_affiliate_video_export_errors import (
    VideoExportDownloadError,
)
from backend.app.services.tiktok_affiliate_video_window import (
    _request_matches_query_window,
)
from erp_api.services.affiliate_center_contract import AffiliateCenterQuery

VIDEO_EXPORT_CREATE_PATH = "/api/v1/oec/affiliate/compass/export_task/create"
VIDEO_EXPORT_DOWNLOAD_PATH = "/api/v1/oec/affiliate/compass/export_task/export"
VIDEO_EXPORT_BUTTON = "[data-testid='export-button']:visible"
VIDEO_EXPORT_TIMEOUT_MS = 180_000
VIDEO_EXPORT_MAX_BYTES = 25 * 1024 * 1024
_DATE_TOKEN = r"(?:\d{4}/\d{1,2}/\d{1,2}|\d{1,2}/\d{1,2}/\d{4})"
_GLOBAL_RANGE = re.compile(fr"^{_DATE_TOKEN}\s*-\s*{_DATE_TOKEN}$")
_GLOBAL_TRIGGER = "[class*='rangePickerScoped']:visible"
_REQUEST_ID_HEADERS = ("request-id", "x-request-id", "x-tt-logid", "x-tt-trace-id")


async def download_video_export(
    page: Page,
    query: AffiliateCenterQuery,
) -> tuple[bytes, str, Download, str | None]:
    download: Download | None = None
    try:
        await select_video_export_window(page, query.window_start, query.window_end)
        async with (
            page.expect_response(
                _is_create_response, timeout=VIDEO_EXPORT_TIMEOUT_MS
            ) as create_info,
            page.expect_download(timeout=VIDEO_EXPORT_TIMEOUT_MS) as download_info,
        ):
            await page.locator(VIDEO_EXPORT_BUTTON).click()
        create_response = await create_info.value
        await _validate_create_response(create_response, query)
        download = await download_info.value
        content = await _read_download(download)
        task_id = await _task_id(create_response)
        return content, task_id, download, await _request_id(create_response)
    except VideoExportDownloadError:
        if download is not None:
            await delete_download(download)
        raise
    except Exception as error:
        if download is not None:
            await delete_download(download)
        raise VideoExportDownloadError(
            "video_export_download_failed", "Video export download failed"
        ) from error


async def select_video_export_window(page: Page, start: date, end: date) -> bool:
    if end < start:
        raise VideoExportDownloadError("window_not_settable", "Invalid video window")
    for attempt in range(2):
        try:
            return await _select_video_export_window_once(page, start, end)
        except VideoExportDownloadError as error:
            if error.category != "window_not_available" or attempt:
                raise
            try:
                await page.reload(wait_until="domcontentloaded", timeout=30_000)
            except Exception as reload_error:
                raise VideoExportDownloadError(
                    "window_not_settable", "Video export page could not be refreshed"
                ) from reload_error
    raise AssertionError("Unreachable video export window retry")


async def _select_video_export_window_once(page: Page, start: date, end: date) -> bool:
    try:
        await page.keyboard.press("Escape")
        await _clear_us_post_date_filter(page)
        range_button = page.get_by_text(_GLOBAL_RANGE, exact=True).first
        if _global_range(await range_button.inner_text()) == (start, end):
            await _dismiss_range_picker(page)
            return False
        trigger = await _open_video_export_picker(page, range_button)
        await _select_date(trigger, start)
        await _select_date(trigger, end)
        await _wait_for_global_range(range_button, start, end)
        await _dismiss_range_picker(page)
        return True
    except VideoExportDownloadError:
        raise
    except Exception as error:
        raise VideoExportDownloadError(
            "window_not_settable", "Video export window could not be selected"
        ) from error


async def _open_video_export_picker(page: Page, range_button: Locator) -> Locator:
    await range_button.click()
    if urlsplit(page.url).hostname == "affiliate-us.tiktok.com":
        await page.get_by_text("Custom", exact=True).last.click()
    else:
        await page.locator(".core-dropdown:visible div.cursor-pointer").last.click()
    trigger = page.locator(_GLOBAL_TRIGGER)
    await trigger.wait_for(state="visible", timeout=30_000)
    return trigger


async def _wait_for_global_range(
    range_button: Locator, start: date, end: date
) -> None:
    for attempt in range(12):
        if _global_range(await range_button.inner_text()) == (start, end):
            return
        if attempt < 11:
            await asyncio.sleep(0.25)
    raise VideoExportDownloadError(
        "window_mismatch", "Video export picker did not retain the target window"
    )


async def _clear_us_post_date_filter(page: Page) -> None:
    if urlsplit(getattr(page, "url", "")).hostname != "affiliate-us.tiktok.com":
        return
    picker = page.locator(".pulse-date-picker-range")
    inputs = picker.locator("input")
    if await inputs.count() < 2:
        return
    values = [await inputs.nth(index).input_value() for index in range(2)]
    if not any(values):
        return
    clear = picker.locator(".core-picker-clear-icon")
    if await clear.count():
        await clear.evaluate("(element) => element.click()")


async def _dismiss_range_picker(page: Page) -> None:
    picker = page.locator(_GLOBAL_TRIGGER)
    if not await picker.is_visible():
        return
    await page.mouse.click(5, 5)
    await picker.wait_for(state="hidden", timeout=3_000)


async def _validate_create_response(
    response: Response, query: AffiliateCenterQuery
) -> None:
    if response.status in {401, 403, 429}:
        category = {401: "session_expired", 403: "http_403", 429: "rate_limited"}
        raise VideoExportDownloadError(
            category[response.status], "Video export rejected"
        )
    if response.status != 200:
        raise VideoExportDownloadError(
            "video_export_request_failed", "Video export request failed"
        )
    body = response.request.post_data_json
    if not _request_matches_query_window(body, query):
        raise VideoExportDownloadError(
            "window_mismatch", "Video export request did not match the ERP window"
        )
    payload = await response.json()
    if not isinstance(payload, dict) or payload.get("code") not in (0, "0"):
        raise VideoExportDownloadError(
            "video_export_response_changed", "Video export response changed"
        )


async def _task_id(response: Response) -> str:
    payload = await response.json()
    data = payload.get("data") if isinstance(payload, dict) else None
    value = data.get("task_id") if isinstance(data, dict) else None
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", value):
        raise VideoExportDownloadError(
            "video_export_response_changed", "Video export task ID is missing"
        )
    return value


async def _read_download(download: Download) -> bytes:
    if not download.suggested_filename.lower().endswith(".xlsx"):
        raise VideoExportDownloadError(
            "video_export_response_changed", "Video export is not XLSX"
        )
    path = Path(await download.path())
    try:
        size = (await asyncio.to_thread(path.stat)).st_size
    except FileNotFoundError:
        with tempfile.TemporaryDirectory(prefix="affiliate-video-export-") as folder:
            recovered = Path(folder) / "export.xlsx"
            await download.save_as(recovered)
            return await _read_bounded_export(recovered)
    if size > VIDEO_EXPORT_MAX_BYTES:
        raise VideoExportDownloadError(
            "video_export_size_limit", "Video export exceeds the size limit"
        )
    return await asyncio.to_thread(path.read_bytes)


async def _read_bounded_export(path: Path) -> bytes:
    if (await asyncio.to_thread(path.stat)).st_size > VIDEO_EXPORT_MAX_BYTES:
        raise VideoExportDownloadError(
            "video_export_size_limit", "Video export exceeds the size limit"
        )
    return await asyncio.to_thread(path.read_bytes)


def _is_create_response(response: Response) -> bool:
    split = urlsplit(response.url)
    return (
        is_affiliate_host(split.hostname)
        and split.path == VIDEO_EXPORT_CREATE_PATH
        and response.request.method.upper() == "POST"
    )


def _picker_date(value: str) -> date | None:
    try:
        return date.fromisoformat(value.replace("/", "-").strip())
    except ValueError:
        match = re.fullmatch(r"(\d{4})/(\d{1,2})/(\d{1,2})", value.strip())
        if match:
            return date(*map(int, match.groups()))
        us_match = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", value.strip())
        return (
            date(int(us_match.group(3)), int(us_match.group(1)), int(us_match.group(2)))
            if us_match
            else None
        )


def _global_range(value: str) -> tuple[date | None, date | None]:
    parts = re.split(r"\s*-\s*", value.strip())
    return (
        tuple(_picker_date(part) for part in parts) if len(parts) == 2 else (None, None)
    )


async def _request_id(response: Response) -> str | None:
    for name in _REQUEST_ID_HEADERS:
        value = await response.header_value(name)
        if value:
            return value[:128]
    return None


async def delete_download(download: Download) -> None:
    try:
        await download.delete()
    except Exception:  # noqa: BLE001 -- exact browser temp file only
        capture_log("affiliate_video_export_cleanup_failed")
