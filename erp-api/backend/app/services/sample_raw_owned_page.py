from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from urllib.parse import parse_qs, urlsplit

import httpx
from playwright.async_api import Page, Playwright

from backend.app.services.hubstudio_attached_browser import (
    connect_attached_hubstudio_browser,
)
from backend.app.services.sample_owned_cdp import owned_sample_cdp
from backend.app.services.sample_owned_page_url import build_owned_sample_url
from backend.app.services.sample_persistent_target import (
    PersistentSampleTarget,
    persistent_sample_key,
)
from backend.app.services.tiktok_affiliate_analytics_page_control import (
    page_security_failure,
)

SAMPLE_HOST = "affiliate.tiktokshopglobalselling.com"
SAMPLE_PATH = "/affiliate/sample/sample-request"


def is_expected_browser_shop(
    targets: list[Mapping[str, object]], platform_shop_id: str
) -> bool:
    visible = {
        value
        for target in targets
        if target.get("type") == "page"
        and isinstance(target.get("url"), str)
        and urlsplit(str(target["url"])).hostname == SAMPLE_HOST
        for value in parse_qs(urlsplit(str(target["url"])).query).get("shop_id", [])
    }
    return visible == {platform_shop_id}


@asynccontextmanager
async def open_owned_sample_page(
    playwright: Playwright,
    cdp_url: str,
    platform_shop_id: str,
    *,
    host: str = SAMPLE_HOST,
    purpose: str = "free",
) -> AsyncIterator[tuple[Page, str]]:
    async with httpx.AsyncClient(timeout=3) as client:
        response = await client.get(f"{cdp_url}/json/list")
        response.raise_for_status()
        targets = response.json()
        persistent_key = persistent_sample_key(platform_shop_id, purpose)
        approved_target_id = None
        if persistent_key:
            version = (await client.get(f"{cdp_url}/json/version")).json()
            registry = PersistentSampleTarget(persistent_key, version["webSocketDebuggerUrl"])
            if registry.path.exists() and registry.is_externally_owned():
                approved_target_id = registry.resolve(targets)
    owned_url = build_owned_sample_url(
        targets, platform_shop_id, host=host, path=SAMPLE_PATH,
        approved_target_id=approved_target_id,
    )
    if host == SAMPLE_HOST and not is_expected_browser_shop(targets, platform_shop_id):
        raise RuntimeError("Browser shop identity is missing or ambiguous")
    if owned_url is None:
        raise RuntimeError("Browser shop identity is missing or ambiguous")
    if (
        persistent_key is None
        and sum(target.get("type") == "page" for target in targets) >= 8
    ):
        raise RuntimeError("tab_limit_reached")
    async with owned_sample_cdp(cdp_url, persistent_key=persistent_key) as endpoint:
        attached = await connect_attached_hubstudio_browser(
            playwright, endpoint, timeout_seconds=15
        )
        pages = [page for context in attached.contexts for page in context.pages]
        if len(pages) != 1 or (
            persistent_key is None and pages[0].url != "about:blank"
        ):
            raise RuntimeError("Collector-owned target is missing or ambiguous")
        try:
            if persistent_key and (failure := await page_security_failure(pages[0])):
                raise RuntimeError(failure[1])
            yield pages[0], owned_url
        except Exception:
            try:
                failure = await asyncio.wait_for(page_security_failure(pages[0]), 2)
            except Exception:  # noqa: BLE001 -- preserve the original capture failure
                failure = None
            if failure:
                raise RuntimeError(failure[1]) from None
            raise
        finally:
            if persistent_key is None:
                await pages[0].close()
