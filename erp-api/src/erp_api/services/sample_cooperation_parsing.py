from __future__ import annotations

import re
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

CHINA_TIMEZONE = ZoneInfo("Asia/Shanghai")
_ZERO_WIDTH = re.compile(r"[\u200b-\u200d\ufeff]")
_OWNER_SEPARATOR = re.compile(r"[,，;/；、\n]+")
_DATE_PATTERN = re.compile(r"^(?:(\d{2}|\d{4})[-./])?(\d{1,2})[-./](\d{1,2})$")


def normalize_account_name(value: Any) -> str:
    text = _plain_text(value)
    if not text:
        return ""
    return "".join(_ZERO_WIDTH.sub("", text).split()).lstrip("@").casefold()


def normalize_bd_name(value: Any) -> str:
    text = _plain_text(value)
    if not text:
        return ""
    return " ".join(_ZERO_WIDTH.sub("", text).split()).casefold()


def split_bd_owners(value: Any) -> tuple[str, ...]:
    text = _plain_text(value)
    if not text:
        return ()
    return tuple(
        dict.fromkeys(
            item.strip() for item in _OWNER_SEPARATOR.split(text) if item.strip()
        )
    )


def is_current_bd_owner(value: Any, current_names: frozenset[str]) -> bool:
    normalized = normalize_bd_name(value)
    return bool(normalized) and any(
        normalized in name or name in normalized for name in current_names
    )


def is_blank_approved_date(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, list):
        return all(is_blank_approved_date(item) for item in value)
    if isinstance(value, dict):
        return not _plain_text(value)
    return False


def parse_approved_date(value: Any, *, today: date) -> date | None:
    if isinstance(value, datetime):
        result = (
            value.astimezone(CHINA_TIMEZONE).date() if value.tzinfo else value.date()
        )
        return result if result <= today else None
    if isinstance(value, date):
        return value if value <= today else None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        seconds = (
            float(value) / 1000
            if abs(float(value)) >= 100_000_000_000
            else float(value)
        )
        try:
            result = (
                datetime.fromtimestamp(seconds, tz=UTC)
                .astimezone(CHINA_TIMEZONE)
                .date()
            )
        except (ValueError, OverflowError, OSError):
            return None
        return result if result <= today else None
    text = _plain_text(value)
    if not text:
        return None
    normalized = text.replace("年", "-").replace("月", "-").replace("日", "").strip()
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        parsed = None
    if parsed is not None:
        result = (
            parsed.astimezone(CHINA_TIMEZONE).date() if parsed.tzinfo else parsed.date()
        )
        return result if result <= today else None
    match = _DATE_PATTERN.fullmatch(normalized)
    if match is None:
        return None
    year_text, month_text, day_text = match.groups()
    year = int(year_text) if year_text else today.year
    if year_text is not None and len(year_text) == 2:
        year += 2000
    try:
        result = date(year, int(month_text), int(day_text))
        if year_text is None and result > today:
            result = result.replace(year=year - 1)
    except ValueError:
        return None
    return result if result <= today else None


def plain_text(value: Any) -> str:
    return _plain_text(value)


def _plain_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "、".join(filter(None, (_plain_text(item) for item in value)))
    if isinstance(value, dict):
        for key in ("name", "text", "value"):
            if key in value:
                return _plain_text(value[key])
    return ""
