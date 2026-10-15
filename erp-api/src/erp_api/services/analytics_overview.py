from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime, time
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

from erp_api.services.analytics_repository import AnalyticsSnapshotInput
from erp_api.services.analytics_resource_types import AnalyticsContentResourceType


def build_overview_snapshots(
    resource_type: AnalyticsContentResourceType,
    intervals: list[dict[str, Any]],
    shop_timezone: ZoneInfo,
    *,
    platform_request_id: str | None,
) -> list[AnalyticsSnapshotInput]:
    snapshots: list[AnalyticsSnapshotInput] = []
    for interval in intervals:
        start = _date(interval, "start_date")
        end = _date(interval, "end_date")
        if (end - start).days != 1:
            raise ValueError(
                "Daily analytics overview intervals must span exactly one shop day."
            )
        metrics = (
            _video_metrics(interval)
            if resource_type == "video"
            else _live_metrics(interval)
        )
        currency = _currency(metrics)
        snapshots.append(
            AnalyticsSnapshotInput(
                metric_set="trend",
                granularity="day",
                window_start=datetime.combine(
                    start, time.min, shop_timezone
                ).astimezone(UTC),
                window_end=datetime.combine(end, time.min, shop_timezone).astimezone(
                    UTC
                ),
                currency=currency,
                metrics=metrics,
                source_updated_at=None,
                platform_request_id=platform_request_id,
            )
        )
    return snapshots


def _video_metrics(interval: Mapping[str, Any]) -> dict[str, object]:
    return _present(
        videoGmv=_money(interval.get("gmv")),
        videoOrders=_number(interval.get("sku_orders")),
        videoProductClicks=_number(interval.get("product_clicks")),
        videoAverageCustomers=_number(interval.get("avg_customers")),
        videoClickThroughRate=_rate(interval.get("click_through_rate")),
    )


def _live_metrics(interval: Mapping[str, Any]) -> dict[str, object]:
    return _present(
        liveGmv=_money(interval.get("gmv")),
        liveOrders=_number(interval.get("sku_orders")),
        liveCustomers=_number(interval.get("customers")),
        liveClickToOrderRate=_rate(interval.get("click_to_order_rate")),
    )


def _money(value: object) -> dict[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    amount, currency = value.get("amount"), value.get("currency")
    if not isinstance(currency, str) or len(currency) != 3:
        return None
    try:
        minor = int(
            (Decimal(str(amount)) * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP)
        )
    except (InvalidOperation, TypeError, ValueError):
        return None
    return {"amountMinor": minor, "currency": currency.upper()}


def _number(value: object) -> int | float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    try:
        parsed = Decimal(str(value))
    except InvalidOperation:
        return None
    return int(parsed) if parsed == parsed.to_integral_value() else float(parsed)


def _rate(value: object) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    percent = text.endswith("%")
    try:
        parsed = Decimal(text[:-1] if percent else text)
    except InvalidOperation:
        return None
    if percent:
        parsed /= 100
    return float(parsed.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def _date(interval: Mapping[str, Any], key: str) -> date:
    value = interval.get(key)
    if not isinstance(value, str):
        raise TypeError(f"Analytics overview interval is missing {key}.")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"Analytics overview interval has invalid {key}.") from error


def _currency(metrics: Mapping[str, object]) -> str:
    money = next(
        (
            value
            for value in metrics.values()
            if isinstance(value, Mapping) and "currency" in value
        ),
        None,
    )
    if not isinstance(money, Mapping) or not isinstance(money.get("currency"), str):
        raise TypeError("Analytics overview interval is missing a currency amount.")
    return money["currency"]


def _present(**values: object) -> dict[str, object]:
    return {key: value for key, value in values.items() if value is not None}
