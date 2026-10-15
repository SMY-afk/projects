from __future__ import annotations

import asyncio
from collections.abc import Mapping
from urllib.parse import parse_qs, urlsplit

from playwright.async_api import Response

from backend.app.services.capture_logging import capture_log as _log

SELLER_PRODUCT_LIST_PATH = "/api/v1/product/local/products/list"
SELLER_PRODUCT_DATA_TYPE = "seller_product_catalog"


class SellerProductCatalogRequester:
    """Request the complete active-product catalog from an observed list call."""

    def __init__(self) -> None:
        self._requested_at: dict[int, float] = {}

    async def request_remaining(
        self,
        response: Response,
        payload: Mapping[str, object],
    ) -> None:
        data = payload.get("data")
        if not isinstance(data, Mapping):
            return
        query = parse_qs(urlsplit(response.url).query)
        tab_id = _query_value(query, "tab_id")
        page_number = _positive_int(data.get("page_number"), default=1)
        page_size = _positive_int(data.get("page_size"), default=50)
        total = _positive_int(data.get("total_product_count"), default=0)

        if tab_id != "1":
            target_page = 1
        elif page_number * page_size < total:
            target_page = page_number + 1
        else:
            return

        now = asyncio.get_running_loop().time()
        last_requested_at = self._requested_at.get(target_page)
        if last_requested_at is not None and now - last_requested_at < 1800:
            return
        self._requested_at[target_page] = now
        try:
            status = await response.frame.page.evaluate(
                """async ({baseUrl, tabId, pageNumber, pageSize}) => {
                    const url = new URL(baseUrl);
                    url.searchParams.set('tab_id', tabId);
                    url.searchParams.set('page_number', String(pageNumber));
                    url.searchParams.set('page_size', String(pageSize));
                    const result = await fetch(url.toString(), {credentials: 'include'});
                    await result.json();
                    return result.status;
                }""",
                {
                    "baseUrl": response.url,
                    "tabId": "1",
                    "pageNumber": target_page,
                    "pageSize": 100,
                },
            )
            if status != 200:
                raise RuntimeError("Product catalog request failed")
            _log("seller_product_catalog_requested", page_number=target_page)
        except Exception as error:  # noqa: BLE001 -- capture boundary records failure
            self._requested_at.pop(target_page, None)
            _log(
                "seller_product_catalog_failed",
                page_number=target_page,
                error_type=type(error).__name__,
                error=str(error)[:300],
            )


def _query_value(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key)
    return values[0] if values else None


def _positive_int(value: object, *, default: int) -> int:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0 else default
