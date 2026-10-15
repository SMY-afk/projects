from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

from erp_api.services.tiktok_data_schemas import (
    TikTokAnalyticsPage,
    parse_analytics_page,
)
from erp_api.services.tiktok_transport import (
    TikTokApiError,
    TikTokRequest,
    TikTokTransport,
)


@dataclass(frozen=True)
class TikTokAnalyticsEndpoint:
    """Endpoint-specific configuration; paths are relative to the API response's data object."""

    path: str
    items_path: str
    next_page_token_path: str | None
    field_map: Mapping[str, str]
    required_fields: tuple[str, ...] = ()
    source_updated_at_path: str | None = None
    item_source_updated_at_path: str | None = None
    status_path: str | None = None
    status_map: Mapping[str, str] = field(default_factory=dict)
    max_window_days: int = 30
    empty_data_as_empty_page: bool = False

    def __post_init__(self) -> None:
        if not self.path.startswith("/"):
            raise ValueError("Analytics endpoint path must start with '/'.")
        if (
            not self.items_path
            or not self.field_map
            or any(not path for path in self.field_map.values())
        ):
            raise ValueError(
                "Analytics endpoint requires an items path and non-empty field map."
            )
        if (
            not set(self.required_fields).issubset(self.field_map)
            or self.max_window_days < 1
        ):
            raise ValueError(
                "Analytics endpoint has invalid required fields or time window."
            )


class TikTokVideoAnalyticsClient(Protocol):
    async def list_videos(
        self,
        access_token: str,
        *,
        shop_cipher: str,
        start_date_ge: str,
        end_date_lt: str,
        page_token: str | None = None,
        page_size: int = 10,
        currency: str = "LOCAL",
        account_type: str = "ALL",
    ) -> TikTokAnalyticsPage: ...

    def iter_videos(
        self,
        access_token: str,
        *,
        shop_cipher: str,
        start_date_ge: str,
        end_date_lt: str,
        page_size: int = 10,
        currency: str = "LOCAL",
        account_type: str = "ALL",
        max_pages: int | None = None,
    ) -> AsyncIterator[TikTokAnalyticsPage]: ...


class TikTokLiveAnalyticsClient(Protocol):
    async def list_lives(
        self,
        access_token: str,
        *,
        shop_cipher: str,
        start_date_ge: str,
        end_date_lt: str,
        page_token: str | None = None,
        page_size: int = 10,
        currency: str = "LOCAL",
        account_type: str = "ALL",
    ) -> TikTokAnalyticsPage: ...

    def iter_lives(
        self,
        access_token: str,
        *,
        shop_cipher: str,
        start_date_ge: str,
        end_date_lt: str,
        page_size: int = 10,
        currency: str = "LOCAL",
        account_type: str = "ALL",
        max_pages: int | None = None,
    ) -> AsyncIterator[TikTokAnalyticsPage]: ...


class HttpTikTokAnalyticsClient(TikTokVideoAnalyticsClient, TikTokLiveAnalyticsClient):
    """Analytics HTTP client that delegates signing, retry, timeout, and logging to TikTokTransport."""

    def __init__(
        self,
        *,
        video_transport: TikTokTransport,
        live_transport: TikTokTransport,
        video_endpoint: TikTokAnalyticsEndpoint,
        live_endpoint: TikTokAnalyticsEndpoint,
    ) -> None:
        self._video_transport = video_transport
        self._live_transport = live_transport
        self._video_endpoint = video_endpoint
        self._live_endpoint = live_endpoint

    async def list_videos(
        self,
        access_token: str,
        *,
        shop_cipher: str,
        start_date_ge: str,
        end_date_lt: str,
        page_token: str | None = None,
        page_size: int = 10,
        currency: str = "LOCAL",
        account_type: str = "ALL",
    ) -> TikTokAnalyticsPage:
        return await self._list(
            self._video_transport,
            self._video_endpoint,
            access_token,
            shop_cipher=shop_cipher,
            start_date_ge=start_date_ge,
            end_date_lt=end_date_lt,
            page_token=page_token,
            page_size=page_size,
            currency=currency,
            account_type=account_type,
        )

    async def list_lives(
        self,
        access_token: str,
        *,
        shop_cipher: str,
        start_date_ge: str,
        end_date_lt: str,
        page_token: str | None = None,
        page_size: int = 10,
        currency: str = "LOCAL",
        account_type: str = "ALL",
    ) -> TikTokAnalyticsPage:
        return await self._list(
            self._live_transport,
            self._live_endpoint,
            access_token,
            shop_cipher=shop_cipher,
            start_date_ge=start_date_ge,
            end_date_lt=end_date_lt,
            page_token=page_token,
            page_size=page_size,
            currency=currency,
            account_type=account_type,
        )

    async def iter_videos(
        self,
        access_token: str,
        *,
        shop_cipher: str,
        start_date_ge: str,
        end_date_lt: str,
        page_size: int = 10,
        currency: str = "LOCAL",
        account_type: str = "ALL",
        max_pages: int | None = None,
    ) -> AsyncIterator[TikTokAnalyticsPage]:
        async for page in self._iterate(
            self._video_transport,
            self._video_endpoint,
            access_token,
            shop_cipher=shop_cipher,
            start_date_ge=start_date_ge,
            end_date_lt=end_date_lt,
            page_size=page_size,
            currency=currency,
            account_type=account_type,
            max_pages=max_pages,
        ):
            yield page

    async def iter_lives(
        self,
        access_token: str,
        *,
        shop_cipher: str,
        start_date_ge: str,
        end_date_lt: str,
        page_size: int = 10,
        currency: str = "LOCAL",
        account_type: str = "ALL",
        max_pages: int | None = None,
    ) -> AsyncIterator[TikTokAnalyticsPage]:
        async for page in self._iterate(
            self._live_transport,
            self._live_endpoint,
            access_token,
            shop_cipher=shop_cipher,
            start_date_ge=start_date_ge,
            end_date_lt=end_date_lt,
            page_size=page_size,
            currency=currency,
            account_type=account_type,
            max_pages=max_pages,
        ):
            yield page

    async def _list(
        self,
        transport: TikTokTransport,
        endpoint: TikTokAnalyticsEndpoint,
        access_token: str,
        *,
        shop_cipher: str,
        start_date_ge: str,
        end_date_lt: str,
        page_token: str | None,
        page_size: int,
        currency: str,
        account_type: str,
    ) -> TikTokAnalyticsPage:
        self._validate_request(
            endpoint, start_date_ge, end_date_lt, page_size, currency
        )
        query = {
            "shop_cipher": shop_cipher,
            "start_date_ge": start_date_ge,
            "end_date_lt": end_date_lt,
            "page_size": str(page_size),
            "currency": currency,
            "account_type": account_type,
            **({"page_token": page_token} if page_token else {}),
        }
        response = await transport.request_with_metadata(
            TikTokRequest("GET", endpoint.path, query=query),
            access_token=access_token,
        )
        return parse_analytics_page(
            response.payload,
            platform_request_id=response.platform_request_id,
            items_path=endpoint.items_path,
            next_page_token_path=endpoint.next_page_token_path,
            field_map=endpoint.field_map,
            required_fields=endpoint.required_fields,
            source_updated_at_path=endpoint.source_updated_at_path,
            item_source_updated_at_path=endpoint.item_source_updated_at_path,
            status_path=endpoint.status_path,
            status_map=endpoint.status_map,
            empty_data_as_empty_page=endpoint.empty_data_as_empty_page,
        )

    @staticmethod
    def _validate_request(
        endpoint: TikTokAnalyticsEndpoint,
        start_date_ge: str,
        end_date_lt: str,
        page_size: int,
        currency: str,
    ) -> None:
        try:
            start_date = date.fromisoformat(start_date_ge)
            end_date = date.fromisoformat(end_date_lt)
        except ValueError as error:
            raise ValueError("Analytics dates must use YYYY-MM-DD.") from error
        if end_date <= start_date:
            raise ValueError("end_date_lt must be later than start_date_ge.")
        if (end_date - start_date).days > endpoint.max_window_days:
            raise ValueError(
                "Analytics date range exceeds the configured maximum window."
            )
        if not 1 <= page_size <= 100:
            raise ValueError("page_size must be between 1 and 100.")
        if currency not in {"LOCAL", "USD"}:
            raise ValueError("currency must be LOCAL or USD.")

    async def _iterate(
        self,
        transport: TikTokTransport,
        endpoint: TikTokAnalyticsEndpoint,
        access_token: str,
        *,
        shop_cipher: str,
        start_date_ge: str,
        end_date_lt: str,
        page_size: int,
        currency: str,
        account_type: str,
        max_pages: int | None,
    ) -> AsyncIterator[TikTokAnalyticsPage]:
        if max_pages is not None and max_pages < 1:
            raise ValueError("max_pages must be positive.")
        current_token: str | None = None
        seen_tokens: set[str] = set()
        pages_read = 0
        while True:
            if current_token:
                if current_token in seen_tokens:
                    raise TikTokApiError(
                        "Analytics pagination returned a repeated page token.",
                        code="pagination_loop",
                        status_code=502,
                    )
                seen_tokens.add(current_token)
            page = await self._list(
                transport,
                endpoint,
                access_token,
                shop_cipher=shop_cipher,
                start_date_ge=start_date_ge,
                end_date_lt=end_date_lt,
                page_token=current_token,
                page_size=page_size,
                currency=currency,
                account_type=account_type,
            )
            yield page
            pages_read += 1
            if not page.next_page_token or (
                max_pages is not None and pages_read >= max_pages
            ):
                return
            current_token = page.next_page_token
