from __future__ import annotations

from collections.abc import AsyncIterator

from erp_api.services.tiktok_return_schemas import (
    TikTokReturnPage,
    parse_return_page_response,
)
from erp_api.services.tiktok_transport import (
    TikTokApiError,
    TikTokRequest,
    TikTokTransport,
)


class HttpTikTokReturnClient:
    def __init__(
        self,
        transport: TikTokTransport,
        path: str = "/return_refund/202602/returns/search",
    ) -> None:
        self._transport = transport
        self._path = path

    async def search_returns(
        self,
        access_token: str,
        *,
        shop_cipher: str,
        page_token: str | None = None,
        page_size: int = 20,
        tenant_id: str | None = None,
        shop_id: str | None = None,
    ) -> TikTokReturnPage:
        if not 1 <= page_size <= 20:
            raise ValueError("page_size must be between 1 and 20.")
        query = {
            "shop_cipher": shop_cipher,
            "page_size": str(page_size),
            "sort_field": "create_time",
            "sort_order": "DESC",
            **({"page_token": page_token} if page_token else {}),
        }
        payload = await self._transport.request(
            TikTokRequest(
                "POST", self._path, query=query, json_body={}, retryable=True
            ),
            access_token=access_token,
            tenant_id=tenant_id,
            shop_id=shop_id,
        )
        return parse_return_page_response(payload)

    async def iter_returns(
        self,
        access_token: str,
        *,
        shop_cipher: str,
        page_size: int = 20,
        max_pages: int | None = None,
        tenant_id: str | None = None,
        shop_id: str | None = None,
    ) -> AsyncIterator[TikTokReturnPage]:
        token: str | None = None
        seen: set[str] = set()
        read = 0
        while True:
            page = await self.search_returns(
                access_token,
                shop_cipher=shop_cipher,
                page_token=token,
                page_size=page_size,
                tenant_id=tenant_id,
                shop_id=shop_id,
            )
            yield page
            read += 1
            if not page.next_page_token or (max_pages and read >= max_pages):
                return
            if page.next_page_token in seen:
                raise TikTokApiError(
                    "TikTok return pagination repeated a page token.",
                    code="pagination_loop",
                    status_code=502,
                )
            seen.add(page.next_page_token)
            token = page.next_page_token
