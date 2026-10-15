import asyncio
from datetime import date

import pytest

from backend.app.services import tiktok_affiliate_available_date as available_date
from backend.app.services.tiktok_affiliate_available_date import (
    _detect_page_date,
    _resource_page,
    _video_range_end,
    detect_latest_selectable_dates,
    latest_date_from_panels,
)


def test_latest_date_comes_from_enabled_tiktok_picker_cells() -> None:
    assert latest_date_from_panels(
        [
            ("2026-08", ["27", "28", "29"]),
            ("2026-09", []),
        ]
    ) == date(2026, 8, 29)


def test_invalid_picker_values_are_ignored() -> None:
    assert latest_date_from_panels([("unknown", ["29"]), ("2026-08", ["x"])]) is None


def test_latest_date_accepts_the_video_picker_month_label() -> None:
    assert latest_date_from_panels(
        [("2026年-8月", ["26", "27"]), ("2026年-9月", [])]
    ) == date(2026, 8, 27)


def test_latest_date_accepts_the_us_video_picker_month_label() -> None:
    assert latest_date_from_panels([("09/2026", ["04", "05"])]) == date(2026, 9, 5)


def test_us_metric_range_end_is_the_latest_available_video_day() -> None:
    assert _video_range_end("08/30/2026 - 09/05/2026") == date(2026, 9, 5)


def test_us_video_availability_uses_enabled_picker_days_not_stale_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Value:
        def __init__(self, text):
            self.text = text

        async def inner_text(self):
            return self.text

        async def all_text_contents(self):
            return self.text

    class Cells:
        async def all_text_contents(self):
            return ["05", "06", "07"]

    class Panel:
        def locator(self, selector):
            return Value("09/2026") if "header-value" in selector else Cells()

    class Panels:
        async def count(self):
            return 1

        def nth(self, index):
            assert index == 0
            return Panel()

    class Trigger:
        async def wait_for(self, **_kwargs):
            return None

        def locator(self, selector):
            assert selector == ".core-panel-date"
            return Panels()

    class Clickable:
        @property
        def first(self):
            return self

        @property
        def last(self):
            return self

        async def click(self):
            return None

        async def inner_text(self):
            return "08/30/2026 - 09/05/2026"

    class Keyboard:
        async def press(self, _key):
            return None

    class Page:
        url = "https://affiliate-us.tiktok.com/affiliate/assets/video-analysis"
        keyboard = Keyboard()

        async def reload(self, **_kwargs):
            return None

        def get_by_text(self, *_args, **_kwargs):
            return Clickable()

        def locator(self, selector):
            if selector == ".core-dropdown:visible div.cursor-pointer":
                return Clickable()
            assert "rangePickerScoped" in selector
            return Trigger()

    async def secure(_page):
        return None

    monkeypatch.setattr(available_date, "page_security_failure", secure)

    assert asyncio.run(_detect_page_date(Page(), "videos")) == date(2026, 9, 7)


def test_video_availability_reloads_stale_page_before_reading_picker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    class Page:
        keyboard = None

        async def reload(self, **kwargs):
            calls.append(("reload", kwargs))

        def get_by_text(self, *args, **kwargs):
            calls.append(("picker", args, kwargs))
            raise RuntimeError("stop after reload")

    async def secure(page):
        return None

    monkeypatch.setattr(available_date, "page_security_failure", secure)

    result = asyncio.run(_detect_page_date(Page(), "videos"))

    assert result is None
    assert calls[0] == (
        "reload",
        {"wait_until": "domcontentloaded", "timeout": 8_000},
    )


def test_reload_timeout_still_reads_an_already_rendered_picker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    class Keyboard:
        async def press(self, key):
            calls.append(("press", key))

    class Page:
        keyboard = Keyboard()

        async def reload(self, **kwargs):
            calls.append(("reload", kwargs))
            raise available_date.PlaywrightTimeoutError("reload timed out")

        def get_by_text(self, *args, **kwargs):
            calls.append(("picker", args, kwargs))
            raise RuntimeError("stop after picker lookup")

    async def secure(page):
        return None

    monkeypatch.setattr(available_date, "page_security_failure", secure)

    result = asyncio.run(_detect_page_date(Page(), "videos"))

    assert result is None
    assert [call[0] for call in calls] == ["reload", "picker", "press"]


def test_temporary_availability_page_is_closed_after_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Page:
        url = available_date._PAGE_URL["creators"]
        close_count = 0

        async def goto(self, url, **kwargs):
            self.url = url

        async def close(self):
            self.close_count += 1

    class Context:
        def __init__(self):
            self.pages = []
            self.page = Page()

        async def new_page(self):
            return self.page

    async def detect(page, resource, **kwargs):
        assert kwargs == {"refresh": False}
        return date(2026, 9, 7)

    context = Context()
    monkeypatch.setattr(available_date, "_detect_page_date", detect)

    result = asyncio.run(
        detect_latest_selectable_dates([context], resources=("creators",))
    )

    assert result == {"creators": date(2026, 9, 7)}
    assert context.page.close_count == 1


def test_us_video_availability_does_not_fall_back_to_picker_when_api_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Page:
        def __init__(self, url: str):
            self.url = url
            self.close_count = 0

        async def goto(self, url, **_kwargs):
            self.url = url

        async def close(self):
            self.close_count += 1

    class Context:
        def __init__(self):
            self.existing = Page(
                "https://affiliate-us.tiktok.com/insights/video-analysis"
                "?shop_region=US&shop_id=9121478993551097445"
            )
            self.fresh = Page("about:blank")
            self.pages = [self.existing]

        async def new_page(self):
            raise AssertionError("Picker fallback must not overstate video availability")

    async def detect_api(source, url):
        assert source is context
        assert "shop_id=9121478993551097445" in url

    context = Context()
    monkeypatch.setattr(available_date, "detect_video_api_latest_day", detect_api)

    result = asyncio.run(available_date._detect_resource_date([context], "videos"))

    assert result is None
    assert context.fresh.close_count == 0
    assert context.existing.close_count == 0


def test_video_availability_waits_for_fresh_picker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Locator:
        @property
        def first(self):
            return self

        async def wait_for(self, **kwargs):
            assert kwargs["state"] == "visible"

        async def click(self):
            return None

    class Page:
        keyboard = None

        async def reload(self, **_kwargs):
            raise AssertionError("A newly opened page must not be reloaded")

        def locator(self, selector):
            if selector == ".pulse-date-picker-range":
                return Locator()
            raise RuntimeError("stop after fresh picker click")

    async def secure(_page):
        return None

    monkeypatch.setattr(available_date, "page_security_failure", secure)

    assert asyncio.run(_detect_page_date(Page(), "videos", refresh=False)) is None


def test_video_availability_waits_until_enabled_days_are_loaded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loaded = False

    class Picker:
        @property
        def first(self):
            return self

        async def wait_for(self, **_kwargs):
            return None

        async def click(self):
            return None

    class EnabledDays:
        @property
        def first(self):
            return self

        async def wait_for(self, **_kwargs):
            nonlocal loaded
            loaded = True

        async def all_text_contents(self):
            return ["01", "02", "03"] if loaded else []

    class Month:
        async def inner_text(self):
            return "2026年-10月"

    class Panel:
        def locator(self, selector):
            return Month() if "header-value" in selector else EnabledDays()

    class Panels(Picker):
        async def count(self):
            return 1

        def nth(self, _index):
            return Panel()

    class Keyboard:
        async def press(self, _key):
            return None

    class Page:
        keyboard = Keyboard()

        def locator(self, selector):
            if selector == ".pulse-date-picker-range":
                return Picker()
            if selector == ".core-panel-date:visible":
                return Panels()
            if selector.endswith(
                ".core-picker-cell-in-view:not(.core-picker-cell-disabled)"
            ):
                return EnabledDays()
            raise AssertionError(selector)

    async def secure(_page):
        return None

    monkeypatch.setattr(available_date, "page_security_failure", secure)

    assert asyncio.run(_detect_page_date(Page(), "videos", refresh=False)) == date(
        2026, 10, 3
    )


def test_unmatched_availability_page_is_closed() -> None:
    class Page:
        url = "https://www.tiktok.com/login"
        close_count = 0

        async def goto(self, url, **kwargs):
            return None

        async def close(self):
            self.close_count += 1

    class Context:
        def __init__(self):
            self.pages = []
            self.page = Page()

        async def new_page(self):
            return self.page

    context = Context()

    result = asyncio.run(_resource_page([context], "creators"))

    assert result == (None, False)
    assert context.page.close_count == 1
