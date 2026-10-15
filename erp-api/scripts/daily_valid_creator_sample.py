"""Parse Feishu sample approval dates for the current rolling window."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

BEIJING = ZoneInfo("Asia/Shanghai")


def sample_window_for_day(end: date) -> tuple[date, date]:
    """ERP Skill default: sixty inclusive calendar days ending on ``end``."""
    return end - timedelta(days=59), end


def sample_date(value: object, window: tuple[date, date]) -> date | None:
    """Return a full date even outside the window; resolve yearless dates inside it."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.astimezone(BEIJING).date() if value.tzinfo else value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    if re.fullmatch(r"\d{10,13}", text):
        try:
            stamp = int(text) / (1000 if len(text) == 13 else 1)
            return datetime.fromtimestamp(stamp, UTC).astimezone(BEIJING).date()
        except (OverflowError, ValueError):
            return None
    if re.fullmatch(r"\d{5}", text) and 20_000 < int(text) < 80_000:
        return date(1899, 12, 30) + timedelta(days=int(text))
    normalized = (
        text.replace("年", "-").replace("月", "-").replace("日", "")
        .replace("/", "-").replace(".", "-")
    )
    if match := re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", normalized):
        try:
            return date(*(int(part) for part in match.groups()))
        except ValueError:
            return None
    if match := re.fullmatch(r"(\d{1,2})-(\d{1,2})", normalized):
        month, day = (int(part) for part in match.groups())
        candidates = []
        for year in range(window[0].year, window[1].year + 1):
            try:
                candidate = date(year, month, day)
            except ValueError:
                continue
            if window[0] <= candidate <= window[1]:
                candidates.append(candidate)
        return max(candidates) if candidates else None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed.astimezone(BEIJING).date() if parsed.tzinfo else parsed.date()
