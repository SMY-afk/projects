from __future__ import annotations

from collections.abc import Mapping
from decimal import ROUND_CEILING, Decimal, InvalidOperation

from app.parsers.seller_order_parser import SellerOrderParseError

SELLER_VIDEO_COMPLETION_DATA_TYPE = "seller_video_completion"


def seller_video_ids(payload: Mapping[str, object]) -> list[str]:
    data = _mapping(payload.get("data"), "data")
    found: dict[str, None] = {}
    for segment in _list(data.get("segments")):
        for timed_list in _list(segment.get("timed_lists")):
            for stat in _list(timed_list.get("stats")):
                video_meta = _optional_mapping(stat.get("video_meta"))
                video_id = _text(video_meta.get("id"))
                if video_id:
                    found[video_id] = None
    return list(found)


def parse_video_completion_response(
    payload: Mapping[str, object],
) -> list[dict[str, object]]:
    if payload.get("code") not in (None, 0, "0"):
        raise SellerOrderParseError("Video completion response code is not zero")
    data = _mapping(payload.get("data"), "data")
    records: list[dict[str, object]] = []
    for segment in _list(data.get("segments")):
        video_id = _text(segment.get("item_id"))
        if not video_id:
            continue
        indicator = next(
            (
                item
                for item in _list(segment.get("data_list"))
                if item.get("indicator_type") in (1, "1")
            ),
            None,
        )
        if indicator is None:
            continue
        trend_data = _list(indicator.get("trend_data"))
        completion = _completion_point(trend_data)
        if completion is None:
            continue
        second, decimal_value, formatted_value = completion
        retention_stages = _retention_stages(trend_data)
        records.append(
            {
                "platform_id": f"seller_video_completion:{video_id}",
                "data_type": SELLER_VIDEO_COMPLETION_DATA_TYPE,
                "title": f"Video {video_id} completion rate",
                "raw_data": {
                    "source": "seller_video_second_trend",
                    "video_id": video_id,
                    "completion_rate": str(decimal_value),
                    "completion_rate_formatted": formatted_value,
                    "completion_second": second,
                    "calculation": "last_full_second_retention",
                    "retention_stages": retention_stages,
                    "source_segment": dict(segment),
                },
            }
        )
    return records


def _completion_point(
    trend_data: list[Mapping[str, object]],
) -> tuple[int, Decimal, str] | None:
    points = _trend_points(trend_data)
    if len(points) < 2:
        return None
    completion_second = max(points) - 1
    value = _retention_value(points.get(completion_second))
    if value is None:
        return None
    return completion_second, *value


def _retention_stages(
    trend_data: list[Mapping[str, object]],
) -> dict[str, dict[str, object]]:
    points = _trend_points(trend_data)
    if len(points) < 2:
        return {}
    end_boundary = max(points)
    targets = {
        "2s": 2,
        "6s": 6,
        "25%": _percentage_second(end_boundary, "0.25"),
        "50%": _percentage_second(end_boundary, "0.50"),
        "75%": _percentage_second(end_boundary, "0.75"),
        "100%": end_boundary - 1,
    }
    stages: dict[str, dict[str, object]] = {}
    for stage, second in targets.items():
        value = _retention_value(points.get(second))
        if value is None:
            continue
        decimal_value, formatted_value = value
        stages[stage] = {
            "second": second,
            "rate": str(decimal_value),
            "formatted": formatted_value,
        }
    return stages


def _percentage_second(end_boundary: int, ratio: str) -> int:
    return int(
        (Decimal(end_boundary) * Decimal(ratio)).to_integral_value(
            rounding=ROUND_CEILING
        )
    )


def _trend_points(
    trend_data: list[Mapping[str, object]],
) -> dict[int, Mapping[str, object]]:
    points: dict[int, Mapping[str, object]] = {}
    for point in trend_data:
        try:
            second = int(str(point.get("base_time")))
        except (TypeError, ValueError):
            continue
        if second >= 0:
            points[second] = point
    return points


def _retention_value(
    point: Mapping[str, object] | None,
) -> tuple[Decimal, str] | None:
    indicator = _optional_mapping(
        _optional_mapping((point or {}).get("value")).get("base_indicator_value")
    )
    raw_decimal = _text(indicator.get("decimal_value"))
    if raw_decimal is None:
        return None
    try:
        decimal_value = Decimal(raw_decimal)
    except InvalidOperation:
        return None
    if not Decimal(0) <= decimal_value <= Decimal(1):
        return None
    formatted = _text(indicator.get("formatted_value")) or (
        f"{decimal_value * Decimal(100):.2f}%"
    )
    return decimal_value, formatted


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise SellerOrderParseError(f"{field} must be an object")
    return value


def _optional_mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _list(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _text(value: object) -> str | None:
    if value is None or isinstance(value, (dict, list)):
        return None
    parsed = str(value).strip()
    return parsed or None
