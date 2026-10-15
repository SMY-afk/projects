import asyncio
from datetime import date

import pytest

from backend.app.services.tiktok_affiliate_intent_page import (
    _select_creator_date,
    _select_creator_window,
)


class _TextNode:
    def __init__(self, text: str, events: list[str] | None = None) -> None:
        self._text = text
        self._events = events

    async def wait_for(self, **kwargs) -> None:
        assert kwargs == {"state": "visible", "timeout": 30_000}
        if self._events is not None:
            self._events.append("header_wait")

    async def inner_text(self) -> str:
        return self._text


class _Cell(_TextNode):
    def __init__(self, events: list[str]) -> None:
        super().__init__("26")
        self._events = events

    async def hover(self) -> None:
        self._events.append("hover")

    async def click(self) -> None:
        self._events.append("click")


class _Collection:
    def __init__(self, items: list[object]) -> None:
        self._items = items

    async def count(self) -> int:
        return len(self._items)

    def nth(self, index: int):
        return self._items[index]


class _Panel:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    def locator(self, selector: str):
        if selector == ".arco-picker-header-value":
            return _TextNode("2026-07")
        return _Collection([_Cell(self._events)])


class _Trigger:
    def __init__(self, events: list[str]) -> None:
        self._events = events

    def locator(self, selector: str):
        if selector == ".arco-picker-header-value":
            return _Collection(
                [
                    _TextNode("2026-07", self._events),
                    _TextNode("2026-08", self._events),
                ]
            )
        if selector == ".arco-panel-date-inner":
            return _Collection([_Panel(self._events)])
        if selector.startswith(".arco-picker-header-icon"):
            return _Collection([])
        raise AssertionError(f"Unexpected selector: {selector}")

    async def wait_for(self, **kwargs) -> None:
        assert kwargs == {"state": "visible", "timeout": 30_000}
        self._events.append("trigger_wait")


class _Page:
    def __init__(self) -> None:
        self.events: list[str] = []

    def locator(self, selector: str):
        assert selector == ".m4b-date-picker-range-trigger"
        return _Trigger(self.events)


def test_creator_date_cell_is_hovered_before_clicking() -> None:
    page = _Page()

    asyncio.run(_select_creator_date(page, date(2026, 7, 26)))

    assert page.events == ["trigger_wait", "header_wait", "hover", "click"]


class _DelayedPicker:
    def __init__(self) -> None:
        self.events: list[str] = []

    async def wait_for(self, **kwargs) -> None:
        assert kwargs == {"state": "visible", "timeout": 30_000}
        self.events.append("picker_wait")

    def locator(self, selector: str):
        assert selector == "input"
        values = ["2026-09-15", "2026-09-15"]

        class Inputs:
            def nth(self, index: int):
                class Input:
                    async def input_value(self) -> str:
                        return values[index]

                return Input()

        return Inputs()


class _ReadyPage:
    def __init__(self) -> None:
        self.picker = _DelayedPicker()

    def locator(self, selector: str):
        assert selector == ".m4b-date-picker-range"
        return self.picker


def test_creator_window_waits_for_slow_page_before_reading_inputs() -> None:
    page = _ReadyPage()

    asyncio.run(
        _select_creator_window(page, date(2026, 9, 15), date(2026, 9, 15))
    )

    assert page.picker.events == ["picker_wait"]


def test_creator_window_accepts_values_that_settle_after_a_click_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Input:
        def __init__(self, picker, index: int) -> None:
            self.picker = picker
            self.index = index

        async def input_value(self) -> str:
            return self.picker.values[self.index]

    class Inputs:
        def __init__(self, picker) -> None:
            self.picker = picker

        def nth(self, index: int) -> Input:
            return Input(self.picker, index)

    class Picker:
        def __init__(self) -> None:
            self.values = ["2026-09-11", "2026-09-17"]

        async def wait_for(self, **kwargs) -> None:
            assert kwargs == {"state": "visible", "timeout": 30_000}

        def locator(self, selector: str) -> Inputs:
            assert selector == "input"
            return Inputs(self)

        async def click(self) -> None:
            return None

    class Keyboard:
        async def press(self, key: str) -> None:
            assert key == "Escape"

    class Page:
        def __init__(self) -> None:
            self.picker = Picker()
            self.keyboard = Keyboard()

        def locator(self, selector: str) -> Picker:
            assert selector == ".m4b-date-picker-range"
            return self.picker

    page = Page()

    async def select_and_time_out(_, value: date) -> None:
        page.picker.values = ["2026-09-12", "2026-09-18"]
        raise TimeoutError("the page applied the click after Playwright timed out")

    monkeypatch.setattr(
        "backend.app.services.tiktok_affiliate_intent_page._select_creator_date",
        select_and_time_out,
    )

    asyncio.run(
        _select_creator_window(page, date(2026, 9, 12), date(2026, 9, 18))
    )
