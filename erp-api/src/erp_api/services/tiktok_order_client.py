from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Protocol

from erp_api.services.tiktok_order_schemas import (
    TikTokOrder,
    TikTokOrderPage,
    parse_order_detail_response,
    parse_order_page_response,
)
from erp_api.services.tiktok_transport import (
    TikTokApiError,
    TikTokRequest,
    TikTokTransport,
)


class TikTokOrderClient(Protocol):
    async def get_orders(
        self, access_token: str, *, shop_cipher: str, order_ids: list[str]
    ) -> list[TikTokOrder]: ...

    async def get_order(
        self, access_token: str, *, shop_cipher: str, order_id: str
    ) -> TikTokOrder: ...

    def iter_order_pages(
        self,
        access_token: str,
        *,
        shop_cipher: str,
        page_token: str | None = None,
        page_size: int = 50,
        updated_from: datetime | None = None,
        updated_to: datetime | None = None,
        status: str | None = None,
        max_pages: int | None = None,
    ) -> AsyncIterator[TikTokOrderPage]: ...


class HttpTikTokOrderClient:
    def __init__(
        self,
        transport: TikTokTransport,
        *,
        search_path: str = "/order/202309/orders/search",
        detail_path: str = "/order/202309/orders",
    ) -> None:
        self._transport = transport
        self._search_path = search_path
        self._detail_path = detail_path

    async def get_order(
        self, access_token: str, *, shop_cipher: str, order_id: str
    ) -> TikTokOrder:
        payload = await self._transport.request(
            TikTokRequest(
                "GET",
                self._detail_path,
                query={"shop_cipher": shop_cipher, "ids": order_id},
            ),
            access_token=access_token,
        )
        return parse_order_detail_response(payload)

    async def list_orders(
        self,
        access_token: str,
        *,
        shop_cipher: str,
        page_token: str | None = None,
        page_size: int = 50,
        updated_from: datetime | None = None,
        updated_to: datetime | None = None,
        status: str | None = None,
    ) -> TikTokOrderPage:
        if not 1 <= page_size <= 100:
            raise ValueError("page_size must be between 1 and 100.")
        query = {
            "shop_cipher": shop_cipher,
            "page_size": str(page_size),
            **({"page_token": page_token} if page_token else {}),
        }
        body: dict[str, object] = {"sort_order": "ASC"}
        if updated_from:
            body["update_time_ge"] = int(updated_from.timestamp())
        if updated_to:
            body["update_time_lt"] = int(updated_to.timestamp())
        if status:
            body["order_status"] = status
        payload = await self._transport.request(
            # Search is read-only despite POST; retrying cannot create orders.
            TikTokRequest("POST", self._search_path, query=query, json_body=body,
                          retryable=True),
            access_token=access_token,
        )
        return parse_order_page_response(payload)

    async def get_orders(self, access_token: str, *, shop_cipher: str, order_ids: list[str]) -> list[TikTokOrder]:
        if not 1 <= len(order_ids) <= 50 or len(set(order_ids)) != len(order_ids):
            raise ValueError("Order detail batch requires 1 to 50 unique order IDs.")
        payload = await self._transport.request(TikTokRequest("GET", self._detail_path,
            query={"shop_cipher": shop_cipher, "ids": ",".join(order_ids)}), access_token=access_token)
        orders = parse_order_page_response(payload).orders
        identifiers = [item.platform_order_id for item in orders]
        if len(set(identifiers)) != len(identifiers) or not set(identifiers) <= set(order_ids):
            raise ValueError("Official order response does not match the requested batch.")
        return orders

    async def iter_order_pages(
        self,
        access_token: str,
        *,
        shop_cipher: str,
        page_token: str | None = None,
        page_size: int = 50,
        updated_from: datetime | None = None,
        updated_to: datetime | None = None,
        status: str | None = None,
        max_pages: int | None = None,
    ) -> AsyncIterator[TikTokOrderPage]:
        if max_pages is not None and max_pages < 1:
            raise ValueError("max_pages must be positive.")
        seen: set[str] = set()
        current = page_token
        pages = 0
        while True:
            if current and current in seen:
                raise TikTokApiError(
                    "TikTok order pagination returned a repeated page token.",
                    code="pagination_loop",
                    status_code=502,
                )
            if current:
                seen.add(current)
            page = await self.list_orders(
                access_token,
                shop_cipher=shop_cipher,
                page_token=current,
                page_size=page_size,
                updated_from=updated_from,
                updated_to=updated_to,
                status=status,
            )
            yield page
            pages += 1
            if not page.next_page_token or (
                max_pages is not None and pages >= max_pages
            ):
                return
            current = page.next_page_token
