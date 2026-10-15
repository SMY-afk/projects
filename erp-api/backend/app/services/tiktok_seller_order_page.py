from __future__ import annotations

import asyncio
from collections.abc import Sequence
from urllib.parse import urlsplit, urlunsplit

from playwright.async_api import BrowserContext, Page

from app.parsers.seller_order_export_parser import SellerOrderExportParseError

SELLER_CENTER_HOST_SUFFIX = ".tiktokshopglobalselling.com"
SELLER_ORDER_PAGE_PATH = "/order"


def _is_seller_page(page: Page) -> bool:
    hostname = (urlsplit(page.url).hostname or "").casefold()
    return hostname.startswith("seller.") and hostname.endswith(
        SELLER_CENTER_HOST_SUFFIX
    )


def _is_order_page(page: Page) -> bool:
    return _is_seller_page(page) and urlsplit(page.url).path == SELLER_ORDER_PAGE_PATH


async def ensure_seller_order_page(
    contexts: Sequence[BrowserContext],
    *,
    timeout_seconds: float,
    page_creation_timeout_seconds: float = 5.0,
) -> tuple[BrowserContext, Page]:
    if timeout_seconds <= 0 or page_creation_timeout_seconds <= 0:
        raise ValueError("Seller page timeouts must be positive.")
    for context in contexts:
        for page in context.pages:
            if _is_order_page(page):
                return context, page

    for context in contexts:
        seed = next((page for page in context.pages if _is_seller_page(page)), None)
        if seed is None:
            continue
        split = urlsplit(seed.url)
        order_url = urlunsplit(
            (split.scheme, split.netloc, SELLER_ORDER_PAGE_PATH, split.query, "")
        )
        created = False
        try:
            page = await asyncio.wait_for(
                context.new_page(),
                timeout=min(timeout_seconds, page_creation_timeout_seconds),
            )
            created = True
        except Exception:  # noqa: BLE001 -- HubStudio may reject new tabs
            page = seed
        try:
            await page.goto(
                order_url,
                wait_until="domcontentloaded",
                timeout=timeout_seconds * 1000,
            )
        except Exception as error:
            if created:
                await page.close()
            raise SellerOrderExportParseError(
                "Seller Center order page could not be opened"
            ) from error
        if not _is_order_page(page):
            if created:
                await page.close()
            raise SellerOrderExportParseError(
                "Seller Center order page requires an active session"
            )
        return context, page

    raise SellerOrderExportParseError("Seller Center session page is not open")
