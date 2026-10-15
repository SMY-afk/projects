from dataclasses import replace
from datetime import timedelta

from erp_api.services.affiliate_center_contract import AffiliateCenterQuery


def split_daily_queries(query: AffiliateCenterQuery) -> list[AffiliateCenterQuery]:
    return split_bounded_queries(query, max_days=1)


def split_compass_queries(query: AffiliateCenterQuery) -> list[AffiliateCenterQuery]:
    """Partition a window into the 30, 7, and 1 day sizes Compass accepts."""
    result = []
    current = query.window_start
    while current <= query.window_end:
        remaining = (query.window_end - current).days + 1
        days = 30 if remaining >= 30 else 7 if remaining >= 7 else 1
        end = current + timedelta(days=days - 1)
        result.append(replace(query, window_start=current, window_end=end))
        current = end + timedelta(days=1)
    return result


def split_bounded_queries(
    query: AffiliateCenterQuery, *, max_days: int
) -> list[AffiliateCenterQuery]:
    if max_days < 1:
        raise ValueError("max_days must be positive")
    result = []
    current = query.window_start
    while current <= query.window_end:
        end = min(current + timedelta(days=max_days - 1), query.window_end)
        result.append(replace(query, window_start=current, window_end=end))
        current = end + timedelta(days=1)
    return result
