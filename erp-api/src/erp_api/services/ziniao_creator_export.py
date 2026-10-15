from __future__ import annotations

import re
import time
from collections.abc import Iterable, Sequence
from datetime import date
from pathlib import Path

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

from app.parsers.xlsx_worksheet_reader import read_first_worksheet
from erp_api.services.ziniao_selenium import attach_selenium, detach_selenium
from erp_api.services.ziniao_webdriver_client import ZiniaoBrowserSession

_PAGE_URL = "https://affiliate-us.tiktok.com/data/creator-analysis"
_DATE_RANGE = ".m4b-date-picker-range"
_DATE_TRIGGER = ".m4b-date-picker-range-trigger"
_EXPORT_BUTTON = "[data-testid='export-button']"


class ZiniaoCreatorExportError(RuntimeError):
    pass


def export_creator_xlsx(
    session: ZiniaoBrowserSession,
    chromedriver_path: str | Path,
    *,
    window_start: date,
    window_end: date,
    timeout_seconds: float = 180,
) -> Path:
    if session.download_path is None:
        raise ZiniaoCreatorExportError("Ziniao download path is unavailable.")
    driver = attach_selenium(session, chromedriver_path)
    try:
        if "/data/creator-analysis" not in driver.current_url:
            driver.get(_PAGE_URL)
        _wait_for(driver, lambda: _page_ready(driver), timeout_seconds)
        _set_window(driver, window_start, window_end, timeout_seconds)
        expected_total = _wait_for_creator_count_stable(driver, timeout_seconds)
        started_at = time.time_ns()
        button = _lowest_viewport_element(driver, _EXPORT_BUTTON)
        driver.execute_script("arguments[0].click()", button)
        exported = _wait_for_download(
            session.download_path,
            window_start,
            window_end,
            started_at,
            timeout_seconds,
        )
        actual_total = sum(1 for _row in read_first_worksheet(exported.read_bytes())) - 1
        if actual_total != expected_total:
            raise ZiniaoCreatorExportError(
                "Creator XLSX row count did not match the TikTok list total."
            )
        return exported
    finally:
        _detach(driver)


def detect_latest_creator_date(
    session: ZiniaoBrowserSession,
    chromedriver_path: str | Path,
    *,
    up_to: date,
    timeout_seconds: float = 60,
) -> date:
    driver = attach_selenium(session, chromedriver_path)
    try:
        if "/data/creator-analysis" not in driver.current_url:
            driver.get(_PAGE_URL)
        _wait_for(driver, lambda: _page_ready(driver), timeout_seconds)
        driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
        picker = driver.find_element(By.CSS_SELECTOR, _DATE_RANGE)
        driver.execute_script("arguments[0].click()", picker)
        _wait_for(
            driver,
            lambda: bool(driver.find_elements(By.CSS_SELECTOR, _DATE_TRIGGER)),
            timeout_seconds,
        )
        target_month = (up_to.year, up_to.month)
        for _ in range(36):
            panels = _calendar_panels(driver)
            months = [_month_parts(month) for month, _days in panels]
            if any(month >= target_month for month in months):
                latest = latest_enabled_date(panels)
                if latest is None:
                    raise ZiniaoCreatorExportError(
                        "TikTok Creator latest date is unavailable."
                    )
                return min(latest, up_to)
            trigger = driver.find_element(By.CSS_SELECTOR, _DATE_TRIGGER)
            icons = trigger.find_elements(
                By.CSS_SELECTOR,
                ".arco-picker-header-icon:not(.arco-picker-header-icon-hidden)",
            )
            if len(icons) < 3:
                break
            driver.execute_script("arguments[0].click()", icons[2])
            time.sleep(0.15)
        raise ZiniaoCreatorExportError("TikTok Creator latest date was not found.")
    finally:
        try:
            driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
        except Exception:  # noqa: BLE001,S110 -- best-effort picker cleanup
            pass
        _detach(driver)


def latest_enabled_date(
    panels: Iterable[tuple[str, Sequence[str]]],
) -> date | None:
    values = []
    for month, days in panels:
        year, month_number = _month_parts(month)
        for day in days:
            try:
                values.append(date(year, month_number, int(day.strip())))
            except ValueError:
                continue
    return max(values) if values else None


def _calendar_panels(driver) -> list[tuple[str, list[str]]]:
    trigger = driver.find_element(By.CSS_SELECTOR, _DATE_TRIGGER)
    result = []
    for panel in trigger.find_elements(By.CSS_SELECTOR, ".arco-panel-date-inner"):
        month = panel.find_element(By.CSS_SELECTOR, ".arco-picker-header-value").text
        days = [
            cell.text
            for cell in panel.find_elements(
                By.CSS_SELECTOR,
                ".arco-picker-cell-in-view:not(.arco-picker-cell-disabled)",
            )
        ]
        result.append((month.strip(), days))
    return result


def _month_parts(value: str) -> tuple[int, int]:
    try:
        year, month = (int(part) for part in value.strip().split("-"))
        if not 1 <= month <= 12:
            raise ValueError
        return year, month
    except ValueError as error:
        raise ZiniaoCreatorExportError("Creator calendar month is invalid.") from error


def _page_ready(driver) -> bool:
    return (
        driver.execute_script("return document.readyState") == "complete"
        and bool(driver.find_elements(By.CSS_SELECTOR, _DATE_RANGE))
        and bool(driver.find_elements(By.CSS_SELECTOR, _EXPORT_BUTTON))
    )


def _wait_for_creator_count_stable(driver, timeout: float) -> int:
    time.sleep(min(5, timeout / 4))
    deadline = time.monotonic() + timeout
    previous = None
    stable_polls = 0
    while time.monotonic() < deadline:
        current = _creator_count_from_text(
            driver.find_element(By.TAG_NAME, "body").text
        )
        if current is not None and current == previous:
            stable_polls += 1
        else:
            previous = current
            stable_polls = 1 if current is not None else 0
        if current is not None and stable_polls >= 3:
            return current
        time.sleep(1)
    raise ZiniaoCreatorExportError("TikTok Creator list total did not stabilize.")


def _creator_count_from_text(value: str) -> int | None:
    matches = re.findall(r"\b([\d,]+)\s+Affiliates\b", value)
    return int(matches[-1].replace(",", "")) if matches else None


def _set_window(driver, start: date, end: date, timeout: float) -> None:
    expected = [start.isoformat(), end.isoformat()]
    picker = driver.find_element(By.CSS_SELECTOR, _DATE_RANGE)
    if _input_values(picker) == expected:
        return
    driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
    driver.execute_script("arguments[0].click()", picker)
    _wait_for(driver, lambda: bool(driver.find_elements(By.CSS_SELECTOR, _DATE_TRIGGER)), timeout)
    _select_date(driver, start)
    _select_date(driver, end)
    _wait_for(driver, lambda: _input_values(picker) == expected, timeout)


def _input_values(picker) -> list[str]:
    return [item.get_attribute("value") or "" for item in picker.find_elements(By.TAG_NAME, "input")]


def _select_date(driver, target: date) -> None:
    trigger = driver.find_element(By.CSS_SELECTOR, _DATE_TRIGGER)
    headers = trigger.find_elements(By.CSS_SELECTOR, ".arco-picker-header-value")
    if len(headers) < 2:
        raise ZiniaoCreatorExportError("Creator date picker headers changed.")
    year, month = (int(value) for value in headers[0].text.strip().split("-"))
    delta = target.year * 12 + target.month - (year * 12 + month)
    if abs(delta) > 36:
        raise ZiniaoCreatorExportError("Creator date is outside the safe range.")
    for _ in range(abs(delta)):
        icons = trigger.find_elements(
            By.CSS_SELECTOR,
            ".arco-picker-header-icon:not(.arco-picker-header-icon-hidden)",
        )
        if len(icons) < 3:
            raise ZiniaoCreatorExportError("Creator date picker controls changed.")
        driver.execute_script("arguments[0].click()", icons[1 if delta < 0 else 2])
        time.sleep(0.15)
    target_header = f"{target.year:04d}-{target.month:02d}"
    for panel in trigger.find_elements(By.CSS_SELECTOR, ".arco-panel-date-inner"):
        header = panel.find_element(By.CSS_SELECTOR, ".arco-picker-header-value")
        if header.text.strip() != target_header:
            continue
        cells = panel.find_elements(
            By.CSS_SELECTOR,
            ".arco-picker-cell-in-view:not(.arco-picker-cell-disabled)",
        )
        for cell in cells:
            if cell.text.strip() == str(target.day):
                driver.execute_script(
                    "arguments[0].dispatchEvent(new MouseEvent('mouseover',"
                    "{bubbles:true}));arguments[0].click()",
                    cell,
                )
                return
    raise ZiniaoCreatorExportError("Creator date is not selectable.")


def _lowest_viewport_element(driver, selector: str):
    height = driver.execute_script("return window.innerHeight")
    visible = []
    for element in driver.find_elements(By.CSS_SELECTOR, selector):
        rect = element.rect
        if (
            rect["width"] > 0
            and rect["height"] > 0
            and rect["y"] + rect["height"] > 0
            and rect["y"] < height
        ):
            visible.append(element)
    if not visible:
        raise ZiniaoCreatorExportError("Creator export button is not visible.")
    return max(visible, key=lambda item: item.rect["y"])


def _wait_for_download(
    directory: Path,
    start: date,
    end: date,
    started_at: int,
    timeout: float,
) -> Path:
    pattern = f"Creator_List_{start:%Y%m%d}-{end:%Y%m%d}_*.xlsx"
    deadline = time.monotonic() + timeout
    previous: tuple[Path, int] | None = None
    while time.monotonic() < deadline:
        files = sorted(directory.glob(pattern), key=lambda item: item.stat().st_mtime_ns)
        candidates = [item for item in files if item.stat().st_mtime_ns >= started_at]
        if candidates:
            current = (candidates[-1], candidates[-1].stat().st_size)
            if current[1] > 0 and current == previous:
                return current[0]
            previous = current
        time.sleep(0.5)
    raise ZiniaoCreatorExportError("Creator XLSX download timed out.")


def _wait_for(driver, predicate, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if predicate():
                return
        except Exception:  # noqa: BLE001,S110 -- DOM may rerender while waiting
            pass
        time.sleep(0.25)
    raise ZiniaoCreatorExportError("Creator page operation timed out.")


def _detach(driver) -> None:
    detach_selenium(driver)
