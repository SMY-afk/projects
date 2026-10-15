from datetime import date
from types import SimpleNamespace

from erp_api.services.ziniao_creator_export import (
    _creator_count_from_text,
    _lowest_viewport_element,
    latest_enabled_date,
)


class FakeDriver:
    def __init__(self, elements):
        self.elements = elements

    def execute_script(self, _script):
        return 800

    def find_elements(self, _by, _selector):
        return self.elements


def _element(y: float):
    return SimpleNamespace(rect={"x": 10, "y": y, "width": 90, "height": 36})


def test_export_uses_lower_creator_list_button_when_summary_export_is_visible() -> None:
    summary = _element(320)
    creator_list = _element(720)

    result = _lowest_viewport_element(
        FakeDriver([creator_list, summary]),
        "[data-testid='export-button']",
    )

    assert result is creator_list


def test_export_ignores_offscreen_button_copy() -> None:
    offscreen = _element(-80)
    visible = _element(320)

    result = _lowest_viewport_element(
        FakeDriver([offscreen, visible]),
        "[data-testid='export-button']",
    )

    assert result is visible


def test_latest_date_comes_from_tiktok_enabled_calendar_cells() -> None:
    assert latest_enabled_date(
        [("2026-08", ["30", "31"]), ("2026-09", [])]
    ) == date(2026, 8, 31)


def test_creator_count_reads_the_full_tiktok_list_total() -> None:
    assert _creator_count_from_text("All creators\n6,583 Affiliates\nAffiliate GMV") == 6583
