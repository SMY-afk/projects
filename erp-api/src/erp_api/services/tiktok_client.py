from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from erp_api.services.tiktok_schemas import (
    TikTokProductDetail,
    TikTokProductPage,
    TikTokShopIdentity,
    TikTokTokenSet,
    parse_authorized_shops_response,
    parse_product_detail_response,
    parse_product_page_response,
    parse_shop_identity_response,
    parse_token_response,
)
from erp_api.services.tiktok_transport import (
    TikTokApiError,
    TikTokRequest,
    TikTokTransport,
)


class TikTokClient(Protocol):
    async def exchange_code(self, code: str) -> TikTokTokenSet: ...

    async def refresh_access_token(self, refresh_token: str) -> TikTokTokenSet: ...

    async def get_shop_identity(self, access_token: str) -> TikTokShopIdentity: ...

    async def get_authorized_shops(
        self, access_token: str
    ) -> list[TikTokShopIdentity]: ...

    async def get_product_detail(
        self, access_token: str, *, shop_id: str, shop_cipher: str, product_id: str
    ) -> TikTokProductDetail: ...

    async def list_products(
        self,
        access_token: str,
        *,
        shop_id: str | None = None,
        shop_cipher: str | None = None,
        page_token: str | None = None,
        page_size: int = 20,
        search_status: int | None = None,
        seller_sku_list: list[str] | None = None,
        create_time_from: int | None = None,
        create_time_to: int | None = None,
    ) -> TikTokProductPage: ...

    def iter_product_pages(
        self,
        access_token: str,
        *,
        shop_id: str | None = None,
        shop_cipher: str | None = None,
        page_token: str | None = None,
        page_size: int = 20,
        search_status: int | None = None,
        seller_sku_list: list[str] | None = None,
        create_time_from: int | None = None,
        create_time_to: int | None = None,
        max_pages: int | None = None,
    ) -> AsyncIterator[TikTokProductPage]: ...


class HttpTikTokClient:
    def __init__(
        self,
        *,
        auth_transport: TikTokTransport,
        api_transport: TikTokTransport,
        token_path: str,
        identity_path: str,
        refresh_token_path: str | None = None,
        product_path: str = "/product/202502/products/search",
        authorized_shops_path: str = "/authorization/202309/shops",
        product_detail_path: str = "/product/202309/products/{product_id}",
    ) -> None:
        self._auth_transport = auth_transport
        self._api_transport = api_transport
        self._token_path = token_path
        self._refresh_token_path = refresh_token_path or (
            f"{token_path.rsplit('/', 1)[0]}/refresh"
        )
        self._identity_path = identity_path
        self._product_path = product_path
        self._authorized_shops_path = authorized_shops_path
        self._product_detail_path = product_detail_path

    @property
    def api_transport(self) -> TikTokTransport:
        return self._api_transport

    async def exchange_code(self, code: str) -> TikTokTokenSet:
        return await self._request_tokens(
            {"auth_code": code, "grant_type": "authorized_code"}
        )

    async def refresh_access_token(self, refresh_token: str) -> TikTokTokenSet:
        return await self._request_tokens(
            {"refresh_token": refresh_token, "grant_type": "refresh_token"},
            path=self._refresh_token_path,
        )

    async def _request_tokens(
        self,
        payload: dict[str, str],
        *,
        path: str | None = None,
    ) -> TikTokTokenSet:
        body = await self._auth_transport.request(
            TikTokRequest(
                "GET",
                path or self._token_path,
                query=payload,
                signed=False,
                credentials_in_query=True,
                retryable=False,
            )
        )
        return parse_token_response(body)

    async def get_shop_identity(self, access_token: str) -> TikTokShopIdentity:
        body = await self._api_transport.request(
            TikTokRequest("GET", self._identity_path),
            access_token=access_token,
        )
        return parse_shop_identity_response(body)

    async def get_authorized_shops(self, access_token: str) -> list[TikTokShopIdentity]:
        body = await self._api_transport.request(
            TikTokRequest("GET", self._authorized_shops_path),
            access_token=access_token,
        )
        return parse_authorized_shops_response(body)

    async def get_product_detail(
        self, access_token: str, *, shop_id: str, shop_cipher: str, product_id: str
    ) -> TikTokProductDetail:
        body = await self._api_transport.request(
            TikTokRequest(
                "GET",
                self._product_detail_path.format(product_id=product_id),
                query={"shop_id": shop_id, "shop_cipher": shop_cipher},
            ),
            access_token=access_token,
        )
        return parse_product_detail_response(body)

    async def list_products(
        self,
        access_token: str,
        *,
        shop_id: str | None = None,
        shop_cipher: str | None = None,
        page_token: str | None = None,
        page_size: int = 20,
        search_status: int | None = None,
        seller_sku_list: list[str] | None = None,
        create_time_from: int | None = None,
        create_time_to: int | None = None,
    ) -> TikTokProductPage:
        if not 1 <= page_size <= 100:
            raise ValueError("page_size must be between 1 and 100.")
        optional_values: dict[str, object | None] = {
            "search_status": search_status,
            "seller_sku_list": seller_sku_list,
            "create_time_from": create_time_from,
            "create_time_to": create_time_to,
        }
        body = {
            key: value for key, value in optional_values.items() if value is not None
        }
        query: dict[str, str] = {
            "page_size": str(page_size),
            **({"page_token": page_token} if page_token else {}),
            **({"shop_id": shop_id} if shop_id else {}),
            **({"shop_cipher": shop_cipher} if shop_cipher else {}),
        }
        response = await self._api_transport.request(
            TikTokRequest("POST", self._product_path, query=query, json_body=body),
            access_token=access_token,
        )
        return parse_product_page_response(response)

    async def iter_product_pages(
        self,
        access_token: str,
        *,
        shop_id: str | None = None,
        shop_cipher: str | None = None,
        page_token: str | None = None,
        page_size: int = 20,
        search_status: int | None = None,
        seller_sku_list: list[str] | None = None,
        create_time_from: int | None = None,
        create_time_to: int | None = None,
        max_pages: int | None = None,
    ) -> AsyncIterator[TikTokProductPage]:
        if max_pages is not None and max_pages < 1:
            raise ValueError("max_pages must be positive.")
        seen_tokens: set[str] = set()
        current_token = page_token
        pages_read = 0
        products_read = 0
        while True:
            if current_token is not None:
                if current_token in seen_tokens:
                    raise TikTokApiError(
                        "TikTok product pagination returned a repeated page token.",
                        code="pagination_loop",
                        status_code=502,
                    )
                seen_tokens.add(current_token)
            page = await self.list_products(
                access_token,
                shop_id=shop_id,
                shop_cipher=shop_cipher,
                page_token=current_token,
                page_size=page_size,
                search_status=search_status,
                seller_sku_list=seller_sku_list,
                create_time_from=create_time_from,
                create_time_to=create_time_to,
            )
            yield page
            pages_read += 1
            products_read += len(page.products)
            reached_total = (
                page.total_count is not None and products_read >= page.total_count
            )
            if (
                not page.next_page_token
                or reached_total
                or (max_pages is not None and pages_read >= max_pages)
            ):
                return
            current_token = page.next_page_token
