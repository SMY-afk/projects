from collections.abc import Iterable
from datetime import datetime

from erp_api.routers.data_schemas import (
    ContentResponse,
    Freshness,
    OperationalError,
    SnapshotResponse,
    V1Envelope,
)


def snapshot_response(row, *, compose_metrics: bool = False) -> SnapshotResponse:
    return SnapshotResponse(
        metricSet=row.metric_set,
        granularity=row.granularity,
        windowStart=row.window_start,
        windowEnd=row.window_end,
        currency=row.currency,
        metrics=_composed_metrics(row.metrics) if compose_metrics else row.metrics,
        sourceUpdatedAt=row.source_updated_at,
        capturedAt=row.captured_at,
    )


def content_response(row) -> ContentResponse:
    return ContentResponse(
        platformExternalId=row.platform_external_id,
        fields=row.fields,
        sourceStatus=row.source_status,
        status=row.status,
        sourceUpdatedAt=row.source_updated_at,
        observedAt=row.observed_at,
    )


def overview_snapshot(rows) -> SnapshotResponse:
    daily = [_composed_metrics(row.metrics) for row in rows]
    currency = rows[0].currency
    gmv_minor = sum(_money_minor(metrics.get("gmv"), currency) for metrics in daily)
    latest_rate = next(
        (
            metrics["liveClickToOrderRate"]
            for metrics in reversed(daily)
            if "liveClickToOrderRate" in metrics
        ),
        None,
    )
    metrics = {
        "gmv": {"amountMinor": gmv_minor, "currency": currency},
        "orders": sum(_numeric(item.get("orders")) for item in daily),
        "videoProductClicks": sum(
            _numeric(item.get("videoProductClicks")) for item in daily
        ),
        "liveCustomers": sum(_numeric(item.get("liveCustomers")) for item in daily),
        **(
            {"latestLiveClickToOrderRate": latest_rate}
            if latest_rate is not None
            else {}
        ),
    }
    return SnapshotResponse(
        metricSet="overview",
        granularity="day",
        windowStart=min(row.window_start for row in rows),
        windowEnd=max(row.window_end for row in rows),
        currency=currency,
        metrics=metrics,
        sourceUpdatedAt=max(
            (row.source_updated_at for row in rows if row.source_updated_at),
            default=None,
        ),
        capturedAt=max(row.captured_at for row in rows),
    )


def envelope(
    source,
    data,
    timestamps: Iterable[datetime | None],
    *,
    unavailable_message: str = "No local data is available yet.",
) -> V1Envelope:
    as_of = max((value for value in timestamps if value is not None), default=None)
    if as_of is None:
        return V1Envelope(
            source=source,
            data=data,
            freshness=Freshness(isStale=True),
            errors=[
                OperationalError(
                    code="data_unavailable",
                    message=unavailable_message,
                    action="resync",
                )
            ],
        )
    return V1Envelope(
        source=source,
        data=data,
        freshness=Freshness(isStale=False, asOf=as_of),
    )


def _composed_metrics(metrics: dict[str, object]) -> dict[str, object]:
    money_values = [metrics.get("videoGmv"), metrics.get("liveGmv")]
    currency = next(
        (
            value.get("currency")
            for value in money_values
            if isinstance(value, dict) and value.get("currency")
        ),
        None,
    )
    composed = {
        "orders": _numeric(metrics.get("videoOrders"))
        + _numeric(metrics.get("liveOrders")),
        "videoProductClicks": _numeric(metrics.get("videoProductClicks")),
        "liveCustomers": _numeric(metrics.get("liveCustomers")),
    }
    if isinstance(currency, str):
        composed["gmv"] = {
            "amountMinor": sum(_money_minor(value, currency) for value in money_values),
            "currency": currency,
        }
    if metrics.get("liveClickToOrderRate") is not None:
        composed["liveClickToOrderRate"] = metrics["liveClickToOrderRate"]
    return composed


def _money_minor(value: object, currency: str) -> int:
    if not isinstance(value, dict) or value.get("currency") != currency:
        return 0
    amount = value.get("amountMinor")
    return amount if isinstance(amount, int) and not isinstance(amount, bool) else 0


def _numeric(value: object) -> int | float:
    return (
        value if isinstance(value, (int, float)) and not isinstance(value, bool) else 0
    )
