from datetime import date

from backend.app.services.tiktok_affiliate_creator_calendar import navigation_step


def test_calendar_does_not_advance_when_target_is_in_right_panel() -> None:
    assert navigation_step(("2026-08", "2026-09"), date(2026, 9, 4)) == 0


def test_calendar_advances_one_panel_at_a_time() -> None:
    assert navigation_step(("2026-08", "2026-09"), date(2026, 10, 6)) == 1
    assert navigation_step(("2026-09", "2026-10"), date(2026, 10, 6)) == 0
    assert navigation_step(("2026-09", "2026-10"), date(2026, 8, 6)) == -1
