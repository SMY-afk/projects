"""Select an available date only after the export calendar has rendered."""

import re
from datetime import date

from playwright.async_api import Locator

from backend.app.services.tiktok_affiliate_video_export_errors import (
    VideoExportDownloadError,
)


async def _select_date(trigger: Locator, value: date) -> None:
    for _ in range(36):
        panels = trigger.locator(".core-panel-date")
        if not await panels.count():
            await panels.first.wait_for(state="visible", timeout=5_000)
        months = [
            await _panel_month(panels.nth(i)) for i in range(await panels.count())
        ]
        if not months:
            raise VideoExportDownloadError(
                "window_not_settable", "Video calendar has not rendered"
            )
        target = value.year * 12 + value.month
        if target < months[0]:
            await trigger.locator(".core-picker-header-icon").nth(1).click()
            continue
        if target > months[-1]:
            await trigger.locator(".core-picker-header-icon").nth(6).click()
            continue
        panel = panels.nth(months.index(target))
        cells = panel.locator(
            ".core-picker-cell-in-view:not(.core-picker-cell-disabled)"
        )
        for index in range(await cells.count()):
            cell = cells.nth(index)
            day_text = (await cell.inner_text()).strip()
            if day_text.isdecimal() and int(day_text) == value.day:
                await cell.click()
                return
        raise VideoExportDownloadError(
            "window_not_available", "Video export date is not available yet"
        )
    raise VideoExportDownloadError(
        "window_not_settable", "Video export month is outside the supported range"
    )


async def _panel_month(panel: Locator) -> int:
    text = (await panel.locator(".core-picker-header-value").inner_text()).strip()
    match = re.fullmatch(r"(\d{4})\D+(\d{1,2})\D*", text)
    if match is not None:
        year, month = map(int, match.groups())
        return year * 12 + month
    us_match = re.fullmatch(r"(\d{1,2})\D+(\d{4})\D*", text)
    if us_match is None:
        raise VideoExportDownloadError(
            "window_not_settable", "Video export month label changed"
        )
    month, year = map(int, us_match.groups())
    return year * 12 + month
