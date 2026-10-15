from datetime import UTC, datetime

from erp_api.services.dashboard_ranges import (
    order_window,
    realtime_windows,
    timezone_or_utc,
    trend_windows,
)


def test_today_window_uses_requested_timezone_and_comparable_windows() -> None:
    now = datetime(2026, 8, 18, 5, 30, tzinfo=UTC)

    windows = realtime_windows("today", timezone_or_utc("Asia/Shanghai"), now)

    assert windows.current.start == datetime(2026, 8, 17, 16, 0, tzinfo=UTC)
    assert windows.current.end == now
    assert windows.previous.end == windows.current.start
    assert windows.last_year.start == datetime(2026, 8, 10, 16, 0, tzinfo=UTC)


def test_last_month_and_order_ranges_have_expected_boundaries() -> None:
    now = datetime(2026, 8, 18, 5, 30, tzinfo=UTC)
    timezone = timezone_or_utc("UTC")

    trend = trend_windows("lastMonth", timezone, now)
    orders = order_window("last14d", timezone, now)

    assert trend.current.start == datetime(2026, 7, 1, tzinfo=UTC)
    assert trend.current.end == datetime(2026, 8, 1, tzinfo=UTC)
    assert orders.start == datetime(2026, 8, 5, tzinfo=UTC)
    assert orders.end == now


def test_invalid_timezone_is_rejected() -> None:
    try:
        timezone_or_utc("Mars/Olympus")
    except ValueError as error:
        assert "IANA timezone" in str(error)
    else:
        raise AssertionError("invalid timezone must fail")
