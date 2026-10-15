from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from urllib.parse import parse_qs, urlsplit

from playwright.async_api import BrowserContext, Page

from backend.app.services.tiktok_affiliate_intent_types import IntentPageError


def is_scheduled_creator_intent(resource: str, job_id: str) -> bool:
    return resource == "creators" and job_id.startswith("affiliate-schedule:")


def _shop_id(page: Page) -> str | None:
    values = parse_qs(urlsplit(page.url).query).get("shop_id")
    return values[0] if values and values[0] else None


async def open_scheduled_creator_page(
    contexts: Iterable[BrowserContext],
    expected_shop_id: str,
    *,
    is_creator_page: Callable[[Page], bool],
    security_check: Callable[[Page], Awaitable[tuple[str, str] | None]],
    tab_limit: int,
) -> Page:
    sources = [
        (context, page)
        for context in contexts
        for page in context.pages
        if is_creator_page(page) and _shop_id(page) == expected_shop_id
    ]
    contexts_with_sources = {id(context) for context, _ in sources}
    if not sources or len(contexts_with_sources) != 1:
        raise IntentPageError("target_page_missing")
    context, source = sources[0]
    if len(context.pages) >= tab_limit:
        raise IntentPageError("tab_limit_reached")
    page = await context.new_page()
    try:
        await page.goto(source.url, wait_until="domcontentloaded", timeout=30_000)
        if not is_creator_page(page) or _shop_id(page) != expected_shop_id:
            raise IntentPageError("target_page_missing", page=page)
        security = await security_check(page)
        if security is not None:
            raise IntentPageError(security[1], page=page)
        return page
    except Exception:
        await close_owned_page(page)
        raise


async def close_owned_page(page: Page) -> None:
    try:
        await page.close()
    except Exception:  # noqa: BLE001,S110 -- detached owned tab is already closed
        pass
