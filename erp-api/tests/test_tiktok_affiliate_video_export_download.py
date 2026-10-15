import asyncio
from datetime import date
from pathlib import Path

import pytest

from backend.app.services.tiktok_affiliate_video_export_calendar import _panel_month
from backend.app.services.tiktok_affiliate_video_export_download import (
    _GLOBAL_RANGE,
    VIDEO_EXPORT_CREATE_PATH,
    VideoExportDownloadError,
    _is_create_response,
    _open_video_export_picker,
    _picker_date,
    _read_download,
    _select_date,
    _wait_for_global_range,
    select_video_export_window,
)


def test_video_export_can_save_missing_playwright_artifact(tmp_path: Path) -> None:
    class Download:
        suggested_filename = "affiliate-video.xlsx"

        async def path(self):
            return str(tmp_path / "missing-artifact")

        async def save_as(self, target):
            Path(target).write_bytes(b"PK\x03\x04workbook")

    assert asyncio.run(_read_download(Download())) == b"PK\x03\x04workbook"


class _Keyboard:
    async def press(self, key: str) -> None:
        assert key == "Escape"


class _RangeButton:
    def __init__(self) -> None:
        self.clicks = 0

    @property
    def first(self):
        return self

    async def inner_text(self) -> str:
        return "2026/7/27 - 2026/8/25"

    async def click(self) -> None:
        self.clicks += 1


class _Picker:
    async def is_visible(self) -> bool:
        return True

    async def wait_for(self, *, state: str, timeout: int) -> None:
        assert state == "hidden"
        assert timeout == 3_000


class _MissingPicker:
    def locator(self, _selector: str):
        return self

    async def count(self) -> int:
        return 0


class _Mouse:
    def __init__(self) -> None:
        self.clicks = []

    async def click(self, x: int, y: int) -> None:
        self.clicks.append((x, y))


class _Page:
    def __init__(self) -> None:
        self.keyboard = _Keyboard()
        self.mouse = _Mouse()
        self.range_button = _RangeButton()

    def get_by_text(self, pattern, *, exact: bool):
        assert exact is True
        return self.range_button

    def locator(self, selector: str):
        if selector == ".pulse-date-picker-range":
            return _MissingPicker()
        assert "rangePickerScoped" in selector
        return _Picker()


def test_existing_video_export_window_is_not_reselected() -> None:
    page = _Page()

    changed = asyncio.run(
        select_video_export_window(
            page,
            date(2026, 7, 27),
            date(2026, 8, 25),
        )
    )

    assert page.range_button.clicks == 0
    assert page.mouse.clicks == [(5, 5)]
    assert changed is False


def test_us_video_export_response_is_accepted() -> None:
    request = type("Request", (), {"method": "POST"})()
    response = type(
        "Response",
        (),
        {
            "url": f"https://affiliate-us.tiktok.com{VIDEO_EXPORT_CREATE_PATH}",
            "request": request,
        },
    )()

    assert _is_create_response(response)


def test_us_video_export_opens_custom_range_picker() -> None:
    clicks = []

    class Locator:
        @property
        def last(self):
            return self

        async def click(self):
            clicks.append("custom")

        async def wait_for(self, *, state, timeout):
            assert (state, timeout) == ("visible", 30_000)

    class Page:
        url = "https://affiliate-us.tiktok.com/insights/video-analysis"

        def get_by_text(self, value, *, exact):
            assert (value, exact) == ("Custom", True)
            return Locator()

        def locator(self, selector):
            assert "rangePickerScoped" in selector
            return Locator()

    class RangeButton:
        async def click(self):
            clicks.append("range")

    asyncio.run(_open_video_export_picker(Page(), RangeButton()))

    assert clicks == ["range", "custom"]


def test_crossborder_video_export_keeps_existing_picker() -> None:
    clicks = []

    class Locator:
        @property
        def last(self):
            return self

        async def click(self):
            clicks.append("preset")

        async def wait_for(self, *, state, timeout):
            assert (state, timeout) == ("visible", 30_000)

    class Page:
        url = "https://affiliate.tiktokshopglobalselling.com/affiliate/assets/video-analysis"

        def locator(self, selector):
            assert "rangePickerScoped" in selector or "core-dropdown" in selector
            return Locator()

    class RangeButton:
        async def click(self):
            clicks.append("range")

    asyncio.run(_open_video_export_picker(Page(), RangeButton()))

    assert clicks == ["range", "preset"]


def test_video_export_waits_for_selected_range_to_render() -> None:
    class RangeButton:
        def __init__(self):
            self.reads = 0

        async def inner_text(self):
            self.reads += 1
            return (
                "09/28/2026 - 10/04/2026"
                if self.reads < 3
                else "10/03/2026 - 10/04/2026"
            )

    button = RangeButton()

    asyncio.run(_wait_for_global_range(button, date(2026, 10, 3), date(2026, 10, 4)))

    assert button.reads == 3


def test_us_video_picker_date_and_month_formats_are_supported() -> None:
    value = type("Value", (), {"inner_text": lambda self: _async_value("09/2026")})()
    panel = type("Panel", (), {"locator": lambda self, _selector: value})()

    assert _picker_date("09/05/2026") == date(2026, 9, 5)
    assert asyncio.run(_panel_month(panel)) == 2026 * 12 + 9
    assert _GLOBAL_RANGE.fullmatch("08/30/2026 - 09/05/2026")


def test_video_export_picker_accepts_unpadded_first_day() -> None:
    clicked = []

    class Cell:
        async def inner_text(self):
            return "1"

        async def click(self):
            clicked.append(True)

    class Cells:
        async def count(self):
            return 1

        def nth(self, _index):
            return Cell()

    class Header:
        async def inner_text(self):
            return "2026-10"

    class Panel:
        def locator(self, selector):
            return Header() if selector == ".core-picker-header-value" else Cells()

    class Panels:
        async def count(self):
            return 1

        def nth(self, _index):
            return Panel()

    class Trigger:
        def locator(self, selector):
            assert selector == ".core-panel-date"
            return Panels()

    asyncio.run(_select_date(Trigger(), date(2026, 10, 1)))

    assert clicked == [True]


def test_video_export_reloads_once_when_calendar_is_stale(monkeypatch) -> None:
    from backend.app.services import tiktok_affiliate_video_export_download as module

    attempts = []

    async def select_once(_page, _start, _end):
        attempts.append(True)
        if len(attempts) == 1:
            raise VideoExportDownloadError("window_not_available", "stale calendar")
        return True

    async def reload(*, wait_until, timeout):
        assert (wait_until, timeout) == ("domcontentloaded", 30_000)
        attempts.append("reload")

    page = type("Page", (), {"reload": staticmethod(reload)})()
    monkeypatch.setattr(module, "_select_video_export_window_once", select_once)

    assert asyncio.run(
        select_video_export_window(page, date(2026, 10, 1), date(2026, 10, 1))
    )
    assert attempts == [True, "reload", True]


def test_video_export_stops_after_one_stale_calendar_refresh(monkeypatch) -> None:
    from backend.app.services import tiktok_affiliate_video_export_download as module

    async def select_once(_page, _start, _end):
        raise VideoExportDownloadError("window_not_available", "unavailable")

    reloads = []

    async def reload(*, wait_until, timeout):
        reloads.append((wait_until, timeout))

    page = type("Page", (), {"reload": staticmethod(reload)})()
    monkeypatch.setattr(module, "_select_video_export_window_once", select_once)

    with pytest.raises(VideoExportDownloadError, match="unavailable"):
        asyncio.run(
            select_video_export_window(page, date(2026, 10, 1), date(2026, 10, 1))
        )
    assert reloads == [("domcontentloaded", 30_000)]


async def _async_value(value):
    return value
