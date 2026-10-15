from datetime import UTC, date, datetime

from erp_api.services.affiliate_live_account_range import (
    resolve_live_range,
    split_live_range,
)


def test_last_sixty_days_use_shop_local_calendar_boundaries() -> None:
    resolved = resolve_live_range(
        "last60d",
        "America/Los_Angeles",
        datetime(2026, 9, 3, 18, tzinfo=UTC),
    )

    assert resolved.window_start == datetime(2026, 7, 6, 7, tzinfo=UTC)
    assert resolved.window_end == datetime(2026, 9, 4, 7, tzinfo=UTC)


def test_custom_range_uses_inclusive_shop_local_dates() -> None:
    resolved = resolve_live_range(
        "custom",
        "America/Los_Angeles",
        datetime(2026, 9, 3, 18, tzinfo=UTC),
        custom_from=date(2026, 8, 1),
        custom_to=date(2026, 8, 15),
    )

    assert resolved.window_start == datetime(2026, 8, 1, 7, tzinfo=UTC)
    assert resolved.window_end == datetime(2026, 8, 16, 7, tzinfo=UTC)


def test_custom_range_allows_dates_older_than_sixty_days() -> None:
    resolved = resolve_live_range(
        "custom",
        "America/Los_Angeles",
        datetime(2026, 9, 3, 18, tzinfo=UTC),
        custom_from=date(2025, 9, 3),
        custom_to=date(2026, 9, 3),
    )

    assert resolved.window_start == datetime(2025, 9, 3, 7, tzinfo=UTC)
    assert resolved.window_end == datetime(2026, 9, 4, 7, tzinfo=UTC)
    chunks = split_live_range(resolved, "America/Los_Angeles")
    assert len(chunks) == 13
    assert chunks[0].window_start == resolved.window_start
    assert chunks[-1].window_end == resolved.window_end
