from __future__ import annotations

import asyncio
from dataclasses import dataclass
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit
from uuid import UUID

from playwright.async_api import BrowserContext, Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from backend.app.services.tiktok_affiliate_creator_summary_capture import (
    TikTokAffiliateCreatorSummaryCapture,
)
from erp_api.infrastructure.database import Database

SAMPLE_REQUEST_PATH = "/affiliate/sample/sample-request"
CREATOR_DETAILS_PATH = "/affiliate/creator/detail"
SEARCH_PLACEHOLDER = "Search creator name"
SEARCH_SELECTOR = (
    f'input[placeholder="{SEARCH_PLACEHOLDER}"], '
    'input[placeholder="\u641c\u7d22\u8fbe\u4eba\u6635\u79f0"]'
)
CAPTCHA_SELECTOR = "#captcha_container"


@dataclass(frozen=True)
class SampleCreatorDetailsTarget:
    username: str
    outbox_ids: frozenset[UUID]


class TikTokSampleCreatorDetailsCollector:
    """Capture only the Creator details popup opened from Sample requests."""

    def __init__(
        self,
        tenant_id: UUID,
        shop_id: UUID,
        platform_shop_id: str,
        database: Database,
        *,
        response_wait_seconds: float = 10,
    ) -> None:
        if response_wait_seconds <= 0:
            raise ValueError("Creator details response wait must be positive.")
        self._tenant_id = tenant_id
        self._shop_id = shop_id
        self._platform_shop_id = platform_shop_id
        self._database = database
        self._response_wait_ms = round(response_wait_seconds * 1000)

    async def capture(
        self,
        contexts: list[BrowserContext],
        targets: list[SampleCreatorDetailsTarget],
    ) -> int:
        if not targets:
            return 0
        sample_page = _sample_request_page(contexts, self._platform_shop_id)
        sample_page_url = getattr(sample_page, "url", "")
        context = sample_page.context
        capture = TikTokAffiliateCreatorSummaryCapture(
            self._tenant_id,
            self._database,
            asyncio.Lock(),
        )
        response_handler = capture.schedule_response
        context.on("response", response_handler)
        search = sample_page.locator(SEARCH_SELECTOR)
        completed = 0
        detail_page: Page | None = None
        detail_mode = ""
        try:
            await search.wait_for(state="visible", timeout=30_000)
            await ensure_no_captcha(sample_page)
            for target in targets:
                await ensure_no_captcha(sample_page)
                username = _username(target.username)
                await search.fill(username)
                await search.press("Enter")
                rows = sample_page.locator("tr").filter(has_text=username)
                await rows.first.wait_for(state="visible", timeout=30_000)
                if await rows.count() != 1:
                    raise RuntimeError("Sample request creator row is ambiguous.")
                detail_page, detail_mode = await open_creator_details_page(
                    context,
                    sample_page,
                    rows.locator(".pulse-avatar"),
                    self._platform_shop_id,
                    username,
                )
                await detail_page.wait_for_load_state(
                    "domcontentloaded", timeout=60_000
                )
                if not creator_details_identity_matches(
                    detail_page.url,
                    self._platform_shop_id,
                    username,
                ):
                    raise RuntimeError("Creator details page identity does not match.")
                await reload_creator_details_page(
                    detail_page,
                    self._platform_shop_id,
                    username,
                )
                await detail_page.wait_for_timeout(self._response_wait_ms)
                await capture.wait_for_pending()
                if not capture.has_complete_profile(self._shop_id, username):
                    raise RuntimeError("Creator details responses are incomplete.")
                if detail_mode == "sample":
                    await restore_sample_request_page(
                        sample_page,
                        sample_page_url,
                        self._platform_shop_id,
                    )
                    search = sample_page.locator(SEARCH_SELECTOR)
                elif detail_mode == "popup":
                    await detail_page.close()
                detail_page = None
                detail_mode = ""
                completed += 1
        finally:
            context.remove_listener("response", response_handler)
            if detail_page is not None:
                try:
                    if detail_mode == "sample":
                        await restore_sample_request_page(
                            sample_page,
                            sample_page_url,
                            self._platform_shop_id,
                        )
                        search = sample_page.locator(SEARCH_SELECTOR)
                    elif detail_mode == "popup":
                        await detail_page.close()
                except Exception:  # noqa: BLE001,S110 -- best-effort owned tab cleanup
                    pass
            try:
                await search.fill("")
                await search.press("Enter")
            finally:
                await capture.stop()
        return completed


async def open_creator_details_page(
    context: BrowserContext,
    sample_page: Page,
    avatar,
    platform_shop_id: str,
    username: str,
) -> tuple[Page, str]:
    """Open creator details and report whether TikTok reused the sample tab."""
    try:
        async with context.expect_page(timeout=30_000) as page_info:
            await avatar.click(timeout=15_000, force=True)
        return await page_info.value, "popup"
    except PlaywrightTimeoutError:
        if creator_details_identity_matches(
            sample_page.url,
            platform_shop_id,
            username,
        ):
            return sample_page, "sample"
        matching_pages = [
            page
            for page in getattr(context, "pages", ())
            if page is not sample_page
            and creator_details_identity_matches(
                page.url,
                platform_shop_id,
                username,
            )
        ]
        if len(matching_pages) == 1:
            return matching_pages[0], "existing"
        owned_page = await context.new_page()
        try:
            await owned_page.goto(
                creator_details_url(
                    sample_page.url,
                    platform_shop_id,
                    username,
                ),
                wait_until="domcontentloaded",
                timeout=60_000,
            )
            if not creator_details_identity_matches(
                owned_page.url,
                platform_shop_id,
                username,
            ):
                raise RuntimeError("Direct creator details page identity does not match.")
        except Exception:
            await owned_page.close()
            raise
        return owned_page, "popup"


async def restore_sample_request_page(
    page: Page,
    sample_page_url: str,
    platform_shop_id: str,
) -> None:
    """Restore and validate the sample page after a same-tab details visit."""
    await page.goto(sample_page_url, wait_until="domcontentloaded", timeout=60_000)
    if not sample_request_identity_matches(page.url, platform_shop_id):
        raise RuntimeError("Sample requests page identity does not match after restore.")


async def ensure_no_captcha(page: Page) -> None:
    if await page.locator(CAPTCHA_SELECTOR).is_visible():
        raise RuntimeError("TikTok captcha requires operator verification.")


async def reload_creator_details_page(
    page: Page,
    platform_shop_id: str,
    username: str,
) -> None:
    """Reload the owned details tab so TikTok emits all profile responses."""
    await page.reload(wait_until="domcontentloaded", timeout=60_000)
    if not creator_details_identity_matches(page.url, platform_shop_id, username):
        raise RuntimeError("Creator details page identity does not match after reload.")


def creator_details_identity_matches(
    url: str,
    platform_shop_id: str,
    username: str,
) -> bool:
    split = urlsplit(url)
    query = parse_qs(split.query)
    names = query.get("cname", [])
    shops = query.get("shop_id", [])
    return (
        split.path == CREATOR_DETAILS_PATH
        and len(names) == 1
        and len(shops) == 1
        and shops[0] == platform_shop_id
        and _username(names[0]) == _username(username)
    )


def sample_request_identity_matches(url: str, platform_shop_id: str) -> bool:
    split = urlsplit(url)
    query = parse_qs(split.query)
    return (
        split.path == SAMPLE_REQUEST_PATH
        and query.get("shop_id") == [platform_shop_id]
    )


def creator_details_url(
    sample_page_url: str,
    platform_shop_id: str,
    username: str,
) -> str:
    split = urlsplit(sample_page_url)
    return urlunsplit(
        (
            split.scheme,
            split.netloc,
            CREATOR_DETAILS_PATH,
            urlencode({"cname": _username(username), "shop_id": platform_shop_id}),
            "",
        )
    )


def _sample_request_page(contexts: list[BrowserContext], platform_shop_id: str) -> Page:
    pages = []
    for context in contexts:
        for page in context.pages:
            split = urlsplit(page.url)
            query = parse_qs(split.query)
            if split.path == SAMPLE_REQUEST_PATH and query.get("shop_id") == [
                platform_shop_id
            ]:
                pages.append(page)
    if len(pages) != 1:
        raise RuntimeError("Sample requests page is missing or ambiguous.")
    return pages[0]


def _username(value: str) -> str:
    username = value.strip().lstrip("@").casefold()
    if not username or len(username) > 255:
        raise ValueError("Sample request creator username is invalid.")
    return username
