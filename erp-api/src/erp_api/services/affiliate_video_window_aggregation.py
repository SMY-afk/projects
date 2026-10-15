from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from erp_api.services.affiliate_center_contract import (
    AffiliateCenterQuery,
    AffiliateCenterResource,
)

VIDEO_EXPORT_MAX_DAYS = 30
_ADDITIVE_METRICS = (
    "gmvMinor",
    "estimatedCommissionMinor",
    "refundedGmvMinor",
    "orderCount",
    "itemsSold",
    "refundedItems",
    "productImpressions",
    "productClicks",
    "views",
    "likes",
    "comments",
    "shares",
)


@dataclass(frozen=True)
class AggregatedVideoSnapshot:
    platform_video_id: str
    metrics: dict[str, object]
    source_updated_at: datetime | None
    captured_at: datetime


def split_video_query(query: AffiliateCenterQuery) -> list[AffiliateCenterQuery]:
    if query.resource is not AffiliateCenterResource.VIDEOS:
        return [query]
    result = []
    start = query.window_start
    while start <= query.window_end:
        end = min(start + timedelta(days=VIDEO_EXPORT_MAX_DAYS - 1), query.window_end)
        result.append(replace(query, window_start=start, window_end=end))
        start = end + timedelta(days=1)
    return result


def aggregate_video_rows(
    rows: list[tuple[object, object]],
) -> list[tuple[AggregatedVideoSnapshot, object]]:
    grouped: dict[str, list[tuple[object, object]]] = {}
    for snapshot, content in rows:
        grouped.setdefault(snapshot.platform_video_id, []).append((snapshot, content))
    return [_aggregate_video(video_rows) for video_rows in grouped.values()]


def _aggregate_video(
    rows: list[tuple[object, object]],
) -> tuple[AggregatedVideoSnapshot, object]:
    latest_snapshot, latest_content = max(rows, key=lambda row: row[0].captured_at)
    snapshots = [row[0] for row in rows]
    metrics = dict(latest_snapshot.metrics)
    for key in _ADDITIVE_METRICS:
        metrics[key] = _sum_metric(snapshots, key)

    gmv = _decimal(metrics.get("gmvMinor"))
    orders = _decimal(metrics.get("orderCount"))
    views = _decimal(metrics.get("views"))
    impressions = _decimal(metrics.get("productImpressions"))
    clicks = _decimal(metrics.get("productClicks"))
    interactions = sum(
        (_decimal(metrics.get(key)) or Decimal(0))
        for key in ("likes", "comments", "shares")
    )
    metrics["averageOrderValueMinor"] = _integer_ratio(gmv, orders)
    metrics["averageGmvPerBuyerMinor"] = _weighted_integer(
        snapshots, "averageGmvPerBuyerMinor", "orderCount"
    )
    metrics["distinctGpmMinor"] = _integer_ratio(
        gmv * 1000 if gmv is not None else None, views
    )
    metrics["productClickThroughRate"] = _ratio(clicks, impressions)
    metrics["engagementRate"] = _ratio(interactions, views)
    metrics["finishRate"] = _weighted_ratio(snapshots, "finishRate", "views")
    return (
        AggregatedVideoSnapshot(
            platform_video_id=latest_snapshot.platform_video_id,
            metrics=metrics,
            source_updated_at=max(
                (
                    item.source_updated_at
                    for item in snapshots
                    if item.source_updated_at
                ),
                default=None,
            ),
            captured_at=max(item.captured_at for item in snapshots),
        ),
        latest_content,
    )


def _sum_metric(snapshots: list[object], key: str) -> int | str | None:
    values = [_decimal(snapshot.metrics.get(key)) for snapshot in snapshots]
    present = [value for value in values if value is not None]
    if not present:
        return None
    total = sum(present, Decimal(0))
    return (
        int(total)
        if total == total.to_integral_value()
        else format(total.normalize(), "f")
    )


def _weighted_integer(
    snapshots: list[object], value_key: str, weight_key: str
) -> int | None:
    weighted = Decimal(0)
    total_weight = Decimal(0)
    for snapshot in snapshots:
        value = _decimal(snapshot.metrics.get(value_key))
        weight = _decimal(snapshot.metrics.get(weight_key))
        if value is None or weight is None or weight <= 0:
            continue
        weighted += value * weight
        total_weight += weight
    return _integer_ratio(weighted, total_weight)


def _weighted_ratio(
    snapshots: list[object], value_key: str, weight_key: str
) -> str | None:
    weighted = Decimal(0)
    total_weight = Decimal(0)
    for snapshot in snapshots:
        value = _decimal(snapshot.metrics.get(value_key))
        weight = _decimal(snapshot.metrics.get(weight_key))
        if value is None or weight is None or weight <= 0:
            continue
        weighted += value * weight
        total_weight += weight
    return _ratio(weighted, total_weight)


def _integer_ratio(
    numerator: Decimal | None, denominator: Decimal | None
) -> int | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return int((numerator / denominator).quantize(Decimal(1)))


def _ratio(numerator: Decimal | None, denominator: Decimal | None) -> str | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return format((numerator / denominator).normalize(), "f")


def _decimal(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
