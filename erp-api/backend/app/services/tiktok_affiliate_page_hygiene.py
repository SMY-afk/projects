from __future__ import annotations

from collections.abc import Iterable
from urllib.parse import parse_qs, urlencode, urlsplit

from playwright.async_api import BrowserContext, Page

_CREATOR_PATH = "/data/creator-analysis"
_VIDEO_PATH = "/affiliate/assets/video-analysis"
_HOME_PATH = "/affiliate/platform/homepage"


async def ensure_affiliate_resource_pages(
    contexts: Iterable[BrowserContext],
    *,
    created_pages: list[Page] | None = None,
) -> list[Page]:
    from backend.app.services import tiktok_affiliate_intent_page as intent_page

    context_list = list(contexts)
    opened = created_pages if created_pages is not None else []
    shop_ids = intent_page.browser_platform_shop_ids(
        page for context in context_list for page in context.pages
    )
    shop_id = next(iter(shop_ids)) if len(shop_ids) == 1 else None
    try:
        for resource, (expected_path, _) in intent_page.RESOURCE_PAGE.items():
            pages = [
                page
                for context in context_list
                for page in context.pages
                if intent_page._is_intent_resource_page(page, expected_path, resource)
            ]
            await intent_page._ensure_resource_pages(
                context_list,
                pages,
                expected_path,
                resource,
                created_pages=opened,
                page_url=_resource_page_url(
                    context_list,
                    intent_page._RESOURCE_PAGE_URL[resource],
                    expected_path,
                    shop_id,
                ),
            )
    except Exception:
        await close_collector_pages(opened)
        opened.clear()
        raise
    return opened


async def close_excess_creator_pages(pages: Iterable[Page]) -> int:
    """Keep one creator list page and remove stale detail/list duplicates."""
    list_pages: list[tuple[Page, str]] = []
    stale_pages: list[Page] = []
    for page in pages:
        split = urlsplit(page.url)
        if not _is_affiliate_page(split.hostname) or split.path != _CREATOR_PATH:
            continue
        query = parse_qs(split.query)
        if "creator_id" in query:
            stale_pages.append(page)
        else:
            list_pages.append((page, _shop_id(query)))

    known_shop_ids = {shop_id for _, shop_id in list_pages if shop_id}
    inferred_shop_id = next(iter(known_shop_ids)) if len(known_shop_ids) == 1 else ""
    list_pages_by_shop: dict[str, list[Page]] = {}
    for page, shop_id in list_pages:
        list_pages_by_shop.setdefault(shop_id or inferred_shop_id, []).append(page)
    for list_pages in list_pages_by_shop.values():
        if len(list_pages) > 1:
            keep = await _preferred_page(list_pages)
            stale_pages.extend(page for page in list_pages if page is not keep)

    closed = 0
    for page in stale_pages:
        try:
            await page.close()
            closed += 1
        except Exception:  # noqa: BLE001,S112 -- detached tabs are already harmless
            continue
    return closed


async def close_excess_managed_pages(pages: Iterable[Page]) -> int:
    page_list = list(pages)
    closed = await close_excess_creator_pages(page_list)
    managed_groups: dict[tuple[str, str], list[Page]] = {}
    auth_pages = []
    for page in page_list:
        split = urlsplit(page.url)
        if _is_affiliate_page(split.hostname) and split.path in {
            _VIDEO_PATH,
            _HOME_PATH,
        }:
            shop_id = _shop_id(parse_qs(split.query))
            managed_groups.setdefault((split.path, shop_id), []).append(page)
        elif _is_auth_page(split.hostname, split.path):
            auth_pages.append(page)
    for group in (*managed_groups.values(), auth_pages):
        if len(group) < 2:
            continue
        keep = await _preferred_page(group)
        closed += await close_collector_pages(
            page for page in group if page is not keep
        )
    return closed


def _shop_id(query: dict[str, list[str]]) -> str:
    values = query.get("shop_id")
    return values[0] if values else ""


async def close_collector_pages(pages: Iterable[Page]) -> int:
    closed = 0
    seen: set[int] = set()
    for page in pages:
        if id(page) in seen:
            continue
        seen.add(id(page))
        try:
            await page.close()
            closed += 1
        except Exception:  # noqa: BLE001,S112 -- detached tabs are already harmless
            continue
    return closed


def _is_auth_page(hostname: str | None, path: str) -> bool:
    if hostname == "www.tiktok.com" and path.startswith("/ucenter_web/"):
        return True
    return hostname == "seller.tiktokshopglobalselling.com" and path.startswith(
        "/account/"
    )


def _is_affiliate_page(hostname: str | None) -> bool:
    from backend.app.services.tiktok_affiliate_analytics_page_control import (
        is_affiliate_host,
    )

    return is_affiliate_host(hostname)


def _resource_page_url(
    contexts: list[BrowserContext],
    fallback_url: str,
    expected_path: str,
    shop_id: str | None,
) -> str | None:
    for context in contexts:
        for page in context.pages:
            split = urlsplit(page.url)
            if not _is_affiliate_page(split.hostname):
                continue
            source = parse_qs(split.query)
            query = {
                key: source[key][0]
                for key in ("shop_region", "shop_id")
                if source.get(key) and source[key][0]
            }
            if shop_id:
                query["shop_id"] = shop_id
            suffix = f"?{urlencode(query)}" if query else ""
            return f"{split.scheme}://{split.netloc}{expected_path}{suffix}"
    return f"{fallback_url}?{urlencode({'shop_id': shop_id})}" if shop_id else None


async def _preferred_page(pages: list[Page]) -> Page:
    for page in pages:
        try:
            if await page.evaluate("document.hasFocus()"):
                return page
        except Exception:  # noqa: BLE001,S112 -- use the first attached fallback
            continue
    return pages[0]
