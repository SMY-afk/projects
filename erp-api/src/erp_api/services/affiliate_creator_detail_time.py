from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from erp_api.services.affiliate_metric_parse_support import timestamp


def detail_window(
    descriptor: Mapping[str, object], shop_timezone: str | None = None
) -> tuple[datetime, datetime]:
    start = _required_timestamp(
        descriptor, "start", "start_time", shop_timezone=shop_timezone
    )
    end_raw = descriptor.get("end", descriptor.get("end_time"))
    end = _required_timestamp(
        descriptor, "end", "end_time", shop_timezone=shop_timezone
    )
    end = _exclusive_end(end, end_raw)
    return start, end


def _required_timestamp(
    descriptor: Mapping[str, object], *names: str, shop_timezone: str | None
) -> datetime:
    value = next((descriptor[name] for name in names if name in descriptor), None)
    try:
        parsed = timestamp(value, names[0])
    except ValueError:
        parsed = _local_timestamp(value, descriptor, names[0], shop_timezone)
    if parsed is None:
        raise ValueError(f"{names[0]} is required.")
    return parsed.astimezone(UTC)


def _local_timestamp(
    value: object,
    descriptor: Mapping[str, object],
    field: str,
    shop_timezone: str | None,
) -> datetime:
    if not isinstance(value, str):
        raise TypeError(f"{field}: invalid timestamp")
    offset = descriptor.get("timezone_offset")
    if isinstance(offset, bool) or not isinstance(offset, int):
        raise TypeError(f"{field}: timezone_offset is required")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{field}: invalid timestamp") from error
    if parsed.tzinfo is not None:
        return parsed
    if shop_timezone:
        return parsed.replace(tzinfo=ZoneInfo(shop_timezone))
    return parsed.replace(tzinfo=timezone(timedelta(seconds=offset)))


def _exclusive_end(parsed: datetime, raw: object) -> datetime:
    if not isinstance(raw, str):
        return parsed
    try:
        local = datetime.fromisoformat(raw)
    except ValueError:
        return parsed
    if local.time().hour == 23 and local.time().minute == 59:
        return parsed + timedelta(seconds=1)
    return parsed
