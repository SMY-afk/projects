from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from erp_api.services.affiliate_center_contract import AffiliateCenterQuery
from erp_api.services.affiliate_center_payload_contract import (
    require_affiliate_payload,
)


@dataclass(frozen=True)
class CreatorPayloadDimensions:
    platform_shop_id: str
    window_start: date
    window_end: date
    timezone_offset: Decimal
    currency: str | None
    filters: dict[str, object]

    @property
    def timezone_offset_text(self) -> str:
        return format(self.timezone_offset, "f")

    def query_window_end(self, expected: AffiliateCenterQuery | None) -> date:
        if (
            expected is not None
            and self.window_start == expected.window_start
            and self.window_end.toordinal() == expected.window_end.toordinal() + 1
        ):
            return expected.window_end
        return self.window_end


def extract_creator_payload_dimensions(
    payload: Mapping[str, object], approved_filter_fields: Collection[str]
) -> CreatorPayloadDimensions:
    require_affiliate_payload("creators", payload)
    segment = _first_segment(payload)
    creator_filter = _mapping(segment.get("filter"), "filter")
    descriptor = _mapping(segment.get("time_descriptor"), "time_descriptor")
    return CreatorPayloadDimensions(
        platform_shop_id=_required_text(
            creator_filter.get("shop_id"), "filter.shop_id"
        ),
        window_start=_local_date(descriptor.get("start"), "start"),
        window_end=_local_date(descriptor.get("end"), "end"),
        timezone_offset=_timezone_offset(descriptor.get("timezone_offset")),
        currency=_payload_currency(segment),
        filters={
            key: creator_filter[key]
            for key in approved_filter_fields
            if key in creator_filter
        },
    )


def validate_shop_timezone(timezone: str, dimensions: CreatorPayloadDimensions) -> None:
    zone = ZoneInfo(timezone)
    years = range(dimensions.window_start.year, dimensions.window_end.year + 1)
    days = {dimensions.window_start, dimensions.window_end}
    days.update(date(year, month, 15) for year in years for month in (1, 7))
    offsets = {
        Decimal(str(offset.total_seconds() / 3600))
        for day in days
        if (offset := datetime.combine(day, time(hour=12), zone).utcoffset())
        is not None
    }
    if dimensions.timezone_offset not in offsets:
        raise ValueError("Affiliate creator timezone offset does not match its shop.")


def creator_pagination_mode(observation: Mapping[str, object]):
    pagination = observation.get("pagination")
    mode = pagination.get("mode") if isinstance(pagination, Mapping) else None
    return (
        mode if mode in {"page_page_size", "offset", "cursor", "mixed"} else "unknown"
    )


def _first_segment(payload: Mapping[str, object]) -> Mapping[str, object]:
    data = _mapping(payload.get("data"), "data")
    segments = data.get("segments")
    if not isinstance(segments, list) or not segments:
        raise ValueError("Affiliate creator response has no creator segment.")
    return _mapping(segments[0], "segments[0]")


def _payload_currency(segment: Mapping[str, object]) -> str | None:
    currencies: set[str] = set()
    timed_lists = segment.get("timed_lists")
    if not isinstance(timed_lists, list):
        return None
    for timed_list in timed_lists:
        if not isinstance(timed_list, Mapping):
            continue
        stats = timed_list.get("stats")
        if not isinstance(stats, list):
            continue
        for stat in stats:
            if isinstance(stat, Mapping):
                _collect_currency_codes(stat, currencies)
    if len(currencies) > 1:
        raise ValueError("Affiliate creator response contains mixed currencies.")
    return next(iter(currencies), None)


def _collect_currency_codes(value: Mapping[str, object], result: set[str]) -> None:
    for key, item in value.items():
        if key == "currency_code" and isinstance(item, str) and item.strip():
            result.add(item.strip().upper())
        elif isinstance(item, Mapping):
            _collect_currency_codes(item, result)


def _timezone_offset(value: object) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise TypeError("Affiliate creator timezone_offset is invalid.")
    try:
        offset = Decimal(str(value))
    except InvalidOperation as error:
        raise ValueError("Affiliate creator timezone_offset is invalid.") from error
    if abs(offset) > 14 and abs(offset) <= 14 * 3600 and offset % 3600 == 0:
        offset /= 3600
    if not offset.is_finite() or not Decimal(-14) <= offset <= Decimal(14):
        raise ValueError("Affiliate creator timezone_offset is invalid.")
    return offset


def _local_date(value: object, field: str) -> date:
    if not isinstance(value, str):
        raise TypeError(f"Affiliate creator {field} is invalid.")
    try:
        return date.fromisoformat(value)
    except ValueError:
        try:
            local_datetime = datetime.fromisoformat(value)
        except ValueError as error:
            raise ValueError(f"Affiliate creator {field} is invalid.") from error
        if local_datetime.timetz().replace(tzinfo=None) != time():
            raise ValueError(f"Affiliate creator {field} is invalid.")
        local_date = local_datetime.date()
        return local_date - timedelta(days=1) if field == "end" else local_date


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"Affiliate creator {field} is invalid.")
    return value


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Affiliate creator {field} is required.")
    return value.strip()
