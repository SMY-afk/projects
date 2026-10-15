"""Merge non-regressing date observations."""

from datetime import date


def merge_latest_available_dates(
    current: dict[str, date], detected: dict[str, date]
) -> dict[str, date]:
    merged = dict(current)
    for resource, value in detected.items():
        previous = merged.get(resource)
        if previous is None or value > previous:
            merged[resource] = value
    return merged
