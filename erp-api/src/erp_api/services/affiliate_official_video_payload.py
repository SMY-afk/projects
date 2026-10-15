from __future__ import annotations

from datetime import date


def latest_available(payload: dict[str, object]) -> date | None:
    data = payload.get("data")
    value = data.get("latest_available_date") if isinstance(data, dict) else None
    try:
        return date.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None


def total_count(payload: dict[str, object]) -> int | None:
    data = payload.get("data")
    value = data.get("total_count") if isinstance(data, dict) else None
    return value if isinstance(value, int) and not isinstance(value, bool) else None
