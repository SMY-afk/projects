from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

from erp_api.services.analytics_resource_types import AnalyticsContentResourceType
from erp_api.services.tiktok_transport import (
    TikTokApiError,
    TikTokRequest,
    TikTokTransport,
)


@dataclass(frozen=True)
class TikTokOverviewResult:
    intervals: list[dict[str, Any]]
    latest_available_date: date | None
    platform_request_id: str | None
    raw_payload: dict[str, Any]


class HttpTikTokOverviewClient:
    def __init__(
        self,
        *,
        video_transport: TikTokTransport,
        live_transport: TikTokTransport,
        video_path: str,
        live_path: str,
        max_window_days: int = 30,
    ) -> None:
        if not video_path.startswith("/") or not live_path.startswith("/"):
            raise ValueError("Analytics overview endpoint paths must start with '/'.")
        if max_window_days < 1:
            raise ValueError("Analytics overview maximum window must be positive.")
        self._video_transport = video_transport
        self._live_transport = live_transport
        self._video_path = video_path
        self._live_path = live_path
        self._max_window_days = max_window_days

    async def get_overview(
        self,
        resource_type: AnalyticsContentResourceType,
        access_token: str,
        *,
        shop_cipher: str,
        start_date_ge: str,
        end_date_lt: str,
        currency: str = "USD",
        account_type: str = "ALL",
    ) -> TikTokOverviewResult:
        start, end = _validated_window(
            start_date_ge, end_date_lt, self._max_window_days
        )
        if currency not in {"LOCAL", "USD"}:
            raise ValueError("currency must be LOCAL or USD.")
        transport = (
            self._video_transport if resource_type == "video" else self._live_transport
        )
        path = self._video_path if resource_type == "video" else self._live_path
        response = await transport.request_with_metadata(
            TikTokRequest(
                "GET",
                path,
                query={
                    "shop_cipher": shop_cipher,
                    "start_date_ge": start.isoformat(),
                    "end_date_lt": end.isoformat(),
                    "granularity": "1D",
                    "currency": currency,
                    "account_type": account_type,
                },
            ),
            access_token=access_token,
        )
        return _parse_overview(response.payload, response.platform_request_id)


def _validated_window(
    start_value: str, end_value: str, max_window_days: int
) -> tuple[date, date]:
    try:
        start, end = date.fromisoformat(start_value), date.fromisoformat(end_value)
    except ValueError as error:
        raise ValueError("Analytics dates must use YYYY-MM-DD.") from error
    if end <= start:
        raise ValueError("end_date_lt must be later than start_date_ge.")
    if (end - start).days > max_window_days:
        raise ValueError("Analytics date range exceeds the configured maximum window.")
    return start, end


def _parse_overview(
    payload: Mapping[str, Any], request_id: str | None
) -> TikTokOverviewResult:
    data = payload.get("data")
    performance = data.get("performance") if isinstance(data, Mapping) else None
    intervals = (
        performance.get("intervals") if isinstance(performance, Mapping) else None
    )
    if not isinstance(intervals, list) or any(
        not isinstance(item, Mapping) for item in intervals
    ):
        raise TikTokApiError(
            "Analytics overview response did not contain valid intervals.",
            code="invalid_analytics_response",
            status_code=502,
            request_id=request_id,
        )
    latest_value = data.get("latest_available_date")
    try:
        latest = (
            date.fromisoformat(latest_value) if isinstance(latest_value, str) else None
        )
    except ValueError as error:
        raise TikTokApiError(
            "Analytics overview response contained an invalid availability date.",
            code="invalid_analytics_response",
            status_code=502,
            request_id=request_id,
        ) from error
    return TikTokOverviewResult(
        intervals=[dict(item) for item in intervals],
        latest_available_date=latest,
        platform_request_id=request_id,
        raw_payload=dict(payload),
    )
