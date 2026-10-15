from __future__ import annotations

from datetime import date as calendar_date
from typing import Literal, Protocol

from erp_api.services.tiktok_bestseller_schemas import (
    BestsellerCurrency,
    BestsellerEntityType,
    TikTokBestsellerPage,
    parse_bestseller_page,
)
from erp_api.services.tiktok_transport import (
    TikTokRequest,
    TikTokTransport,
)

BestsellerTimeSlot = Literal["1D", "7D", "30D"]
BestsellerAuthorType = Literal["ALL", "OFFICIAL", "CHANNEL", "AFFILIATE"]

BESTSELLER_ENDPOINTS: dict[BestsellerEntityType, str] = {
    "product": "/analytics/202511/products/bestselling",
    "creator": "/analytics/202511/creators/bestselling",
    "video": "/analytics/202511/videos/bestselling",
    "live": "/analytics/202511/lives/bestselling",
}


class TikTokBestsellerClient(Protocol):
    async def list_products(
        self,
        access_token: str,
        *,
        shop_cipher: str,
        date: str,
        time_slot: BestsellerTimeSlot,
        currency: BestsellerCurrency,
    ) -> TikTokBestsellerPage: ...

    async def list_creators(
        self,
        access_token: str,
        *,
        shop_cipher: str,
        date: str,
        time_slot: BestsellerTimeSlot,
        currency: BestsellerCurrency,
        author_type: BestsellerAuthorType,
    ) -> TikTokBestsellerPage: ...

    async def list_videos(
        self,
        access_token: str,
        *,
        shop_cipher: str,
        date: str,
        time_slot: BestsellerTimeSlot,
        currency: BestsellerCurrency,
    ) -> TikTokBestsellerPage: ...

    async def list_lives(
        self,
        access_token: str,
        *,
        shop_cipher: str,
        date: str,
        time_slot: BestsellerTimeSlot,
        currency: BestsellerCurrency,
    ) -> TikTokBestsellerPage: ...


class HttpTikTokBestsellerClient:
    """Bestsellers client delegating signing, retries, and timeouts to transport."""

    def __init__(self, transport: TikTokTransport) -> None:
        self._transport = transport

    async def list_products(
        self,
        access_token: str,
        *,
        shop_cipher: str,
        date: str,
        time_slot: BestsellerTimeSlot,
        currency: BestsellerCurrency,
    ) -> TikTokBestsellerPage:
        return await self._list(
            "product",
            access_token,
            shop_cipher=shop_cipher,
            date=date,
            time_slot=time_slot,
            currency=currency,
        )

    async def list_creators(
        self,
        access_token: str,
        *,
        shop_cipher: str,
        date: str,
        time_slot: BestsellerTimeSlot,
        currency: BestsellerCurrency,
        author_type: BestsellerAuthorType,
    ) -> TikTokBestsellerPage:
        return await self._list(
            "creator",
            access_token,
            shop_cipher=shop_cipher,
            date=date,
            time_slot=time_slot,
            currency=currency,
            author_type=author_type,
        )

    async def list_videos(
        self,
        access_token: str,
        *,
        shop_cipher: str,
        date: str,
        time_slot: BestsellerTimeSlot,
        currency: BestsellerCurrency,
    ) -> TikTokBestsellerPage:
        return await self._list(
            "video",
            access_token,
            shop_cipher=shop_cipher,
            date=date,
            time_slot=time_slot,
            currency=currency,
        )

    async def list_lives(
        self,
        access_token: str,
        *,
        shop_cipher: str,
        date: str,
        time_slot: BestsellerTimeSlot,
        currency: BestsellerCurrency,
    ) -> TikTokBestsellerPage:
        return await self._list(
            "live",
            access_token,
            shop_cipher=shop_cipher,
            date=date,
            time_slot=time_slot,
            currency=currency,
        )

    async def _list(
        self,
        entity_type: BestsellerEntityType,
        access_token: str,
        *,
        shop_cipher: str,
        date: str,
        time_slot: BestsellerTimeSlot,
        currency: BestsellerCurrency,
        author_type: BestsellerAuthorType | None = None,
    ) -> TikTokBestsellerPage:
        self._validate_request(
            shop_cipher=shop_cipher,
            date=date,
            time_slot=time_slot,
            currency=currency,
            author_type=author_type,
            creators=entity_type == "creator",
        )
        query = {
            "shop_cipher": shop_cipher,
            "date": date,
            "time_slot": time_slot,
            "currency": currency,
        }
        if author_type:
            query["author_type"] = author_type
        response = await self._transport.request_with_metadata(
            TikTokRequest("GET", BESTSELLER_ENDPOINTS[entity_type], query=query),
            access_token=access_token,
        )
        return parse_bestseller_page(
            response.payload,
            entity_type=entity_type,
            currency=currency,
            platform_request_id=response.platform_request_id,
        )

    @staticmethod
    def _validate_request(
        *,
        shop_cipher: str,
        date: str,
        time_slot: str,
        currency: str,
        author_type: str | None,
        creators: bool,
    ) -> None:
        if not shop_cipher:
            raise ValueError("shop_cipher is required.")
        try:
            parsed_date = calendar_date.fromisoformat(date)
        except ValueError as error:
            raise ValueError("date must use YYYY-MM-DD.") from error
        if parsed_date.isoformat() != date:
            raise ValueError("date must use YYYY-MM-DD.")
        if time_slot not in {"1D", "7D", "30D"}:
            raise ValueError("time_slot must be 1D, 7D, or 30D.")
        if currency not in {"USD", "LOCAL"}:
            raise ValueError("currency must be USD or LOCAL.")
        allowed_authors = {"ALL", "OFFICIAL", "CHANNEL", "AFFILIATE"}
        if creators and author_type not in allowed_authors:
            raise ValueError("author_type is invalid.")
