from __future__ import annotations

from datetime import date as calendar_date
from typing import Any, Literal

from erp_api.services.tiktok_bestseller_client import BESTSELLER_ENDPOINTS
from erp_api.services.tiktok_transport import (
    TikTokApiError,
    TikTokRequest,
    TikTokTransport,
)

TimeSlot = Literal["1D", "7D", "30D"]
Currency = Literal["USD", "LOCAL"]
AuthorType = Literal["ALL", "OFFICIAL", "CHANNEL", "AFFILIATE"]

ENDPOINTS = (
    ("products", BESTSELLER_ENDPOINTS["product"]),
    ("creators", BESTSELLER_ENDPOINTS["creator"]),
    ("videos", BESTSELLER_ENDPOINTS["video"]),
    ("lives", BESTSELLER_ENDPOINTS["live"]),
)


class TikTokBestsellerProbe:
    def __init__(self, transport: TikTokTransport) -> None:
        self._transport = transport

    async def run(
        self,
        *,
        access_token: str,
        shop_cipher: str,
        date: str,
        time_slot: TimeSlot,
        currency: Currency,
        author_type: AuthorType = "ALL",
    ) -> list[dict[str, Any]]:
        self._validate(date, time_slot, currency, author_type)
        common_query = {
            "shop_cipher": shop_cipher,
            "date": date,
            "time_slot": time_slot,
            "currency": currency,
        }
        results: list[dict[str, Any]] = []
        for api, path in ENDPOINTS:
            query = dict(common_query)
            if api == "creators":
                query["author_type"] = author_type
            try:
                response = await self._transport.request_with_metadata(
                    TikTokRequest("GET", path, query=query),
                    access_token=access_token,
                )
            except TikTokApiError as error:
                results.append(
                    {
                        "api": api,
                        "httpStatus": error.upstream_status_code,
                        "tiktokCode": error.code,
                        "requestId": error.request_id,
                        "fieldNames": {"envelope": [], "data": [], "item": []},
                    }
                )
                continue
            results.append(
                {
                    "api": api,
                    "httpStatus": response.status_code,
                    "tiktokCode": response.payload.get("code"),
                    "requestId": response.platform_request_id,
                    "fieldNames": self._field_names(response.payload),
                }
            )
        return results

    @staticmethod
    def _validate(
        date: str,
        time_slot: str,
        currency: str,
        author_type: str,
    ) -> None:
        if calendar_date.fromisoformat(date).isoformat() != date:
            raise ValueError("date must use YYYY-MM-DD format.")
        if time_slot not in {"1D", "7D", "30D"}:
            raise ValueError("time_slot must be 1D, 7D, or 30D.")
        if currency not in {"USD", "LOCAL"}:
            raise ValueError("currency must be USD or LOCAL.")
        if author_type not in {"ALL", "OFFICIAL", "CHANNEL", "AFFILIATE"}:
            raise ValueError("author_type is invalid.")

    @staticmethod
    def _field_names(payload: dict[str, Any]) -> dict[str, list[str]]:
        data = payload.get("data")
        data_object = data if isinstance(data, dict) else {}
        first_item: dict[str, Any] = {}
        for value in data_object.values():
            if isinstance(value, list) and value and isinstance(value[0], dict):
                first_item = value[0]
                break
        return {
            "envelope": sorted(payload),
            "data": sorted(data_object),
            "item": sorted(first_item),
        }
