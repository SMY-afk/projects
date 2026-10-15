import asyncio

import pytest

from backend.app.services.tiktok_affiliate_intent_types import IntentPageError
from backend.app.services.tiktok_affiliate_page_hygiene import (
    close_collector_pages,
    close_excess_creator_pages,
    close_excess_managed_pages,
    ensure_affiliate_resource_pages,
)


class FakePage:
    def __init__(self, url: str, *, focused: bool = False) -> None:
        self.url = url
        self.focused = focused
        self.closed = False

    async def evaluate(self, _script: str) -> bool:
        return self.focused

    async def close(self) -> None:
        self.closed = True


def test_keeps_one_creator_list_and_closes_stale_creator_tabs() -> None:
    base = "https://affiliate.tiktokshopglobalselling.com/data/creator-analysis"
    first = FakePage(base)
    focused = FakePage(base + "?shop_id=1", focused=True)
    detail_a = FakePage(base + "?creator_id=a&shop_id=1")
    detail_b = FakePage(base + "?creator_id=b&shop_id=1")
    video = FakePage(
        "https://affiliate.tiktokshopglobalselling.com/affiliate/assets/video-analysis"
    )

    closed = asyncio.run(
        close_excess_creator_pages([first, focused, detail_a, detail_b, video])
    )

    assert closed == 3
    assert first.closed
    assert not focused.closed
    assert detail_a.closed
    assert detail_b.closed
    assert not video.closed


def test_does_not_touch_the_only_creator_list_page() -> None:
    page = FakePage(
        "https://affiliate.tiktokshopglobalselling.com/data/creator-analysis"
    )

    assert asyncio.run(close_excess_creator_pages([page])) == 0
    assert not page.closed


def test_closes_duplicate_auth_redirects_but_keeps_one_for_manual_login() -> None:
    focused = FakePage(
        "https://seller.tiktokshopglobalselling.com/account/login", focused=True
    )
    duplicate = FakePage("https://seller.tiktokshopglobalselling.com/account/login")
    ucenter = FakePage("https://www.tiktok.com/ucenter_web/zti_web")
    unrelated = FakePage("https://example.com/orders")

    closed = asyncio.run(
        close_excess_managed_pages([focused, duplicate, ucenter, unrelated])
    )

    assert closed == 2
    assert not focused.closed
    assert duplicate.closed
    assert ucenter.closed
    assert not unrelated.closed


def test_closes_duplicate_homepages_only_within_the_same_shop() -> None:
    base = "https://affiliate.tiktokshopglobalselling.com/affiliate/platform/homepage"
    duplicate = FakePage(base + "?shop_id=platform-shop-1")
    focused = FakePage(base + "?shop_id=platform-shop-1", focused=True)
    other_shop = FakePage(base + "?shop_id=platform-shop-2")

    closed = asyncio.run(close_excess_managed_pages([duplicate, focused, other_shop]))

    assert closed == 1
    assert duplicate.closed
    assert not focused.closed
    assert not other_shop.closed


def test_closes_pages_created_by_the_collector() -> None:
    created = [FakePage("about:blank"), FakePage("https://example.com")]

    assert asyncio.run(close_collector_pages(created)) == 2
    assert all(page.closed for page in created)


def test_redirected_resource_page_is_closed_and_reported_as_expired() -> None:
    class RedirectPage(FakePage):
        async def goto(self, _url, **_kwargs) -> None:
            self.url = "https://seller.tiktokshopglobalselling.com/account/login"

    class Context:
        def __init__(self) -> None:
            self.pages = []

        async def new_page(self):
            page = RedirectPage("about:blank")
            self.pages.append(page)
            return page

    context = Context()
    created = []

    with pytest.raises(IntentPageError) as error:
        asyncio.run(ensure_affiliate_resource_pages([context], created_pages=created))

    assert error.value.category == "session_expired"
    assert context.pages[0].closed
    assert created == []


def test_missing_resource_page_inherits_the_open_shop_context() -> None:
    opened = []

    class Page(FakePage):
        async def goto(self, url, **_kwargs) -> None:
            opened.append(url)
            self.url = url

    class Context:
        def __init__(self) -> None:
            self.pages = [
                Page(
                    "https://affiliate.tiktokshopglobalselling.com/data/creator-analysis"
                    "?shop_id=platform-shop-1"
                )
            ]

        async def new_page(self):
            page = Page("about:blank")
            self.pages.append(page)
            return page

    asyncio.run(ensure_affiliate_resource_pages([Context()]))

    assert opened == [
        (
            "https://affiliate.tiktokshopglobalselling.com/affiliate/assets/video-analysis"
            "?shop_id=platform-shop-1"
        )
    ]


def test_reuses_open_us_affiliate_pages_without_opening_global_pages() -> None:
    opened = []

    class Context:
        def __init__(self) -> None:
            self.pages = [
                FakePage(
                    "https://affiliate-us.tiktok.com/data/creator-analysis"
                    "?shop_region=US&shop_id=platform-shop-1"
                ),
                FakePage(
                    "https://affiliate-us.tiktok.com/affiliate/assets/video-analysis"
                    "?shop_region=US&shop_id=platform-shop-1"
                ),
            ]

        async def new_page(self):
            opened.append(True)
            return FakePage("about:blank")

    assert asyncio.run(ensure_affiliate_resource_pages([Context()])) == []
    assert opened == []


def test_missing_us_resource_page_keeps_the_us_origin_and_region() -> None:
    opened = []

    class Page(FakePage):
        async def goto(self, url, **_kwargs) -> None:
            opened.append(url)
            self.url = url

    class Context:
        def __init__(self) -> None:
            self.pages = [
                Page(
                    "https://affiliate-us.tiktok.com/data/creator-analysis"
                    "?shop_region=US&shop_id=platform-shop-1"
                )
            ]

        async def new_page(self):
            page = Page("about:blank")
            self.pages.append(page)
            return page

    asyncio.run(ensure_affiliate_resource_pages([Context()]))

    assert opened == [
        (
            "https://affiliate-us.tiktok.com/affiliate/assets/video-analysis"
            "?shop_region=US&shop_id=platform-shop-1"
        )
    ]


def test_refuses_to_open_a_page_after_the_context_tab_limit(monkeypatch) -> None:
    class Context:
        def __init__(self) -> None:
            self.pages = [
                FakePage("https://example.com/1"),
                FakePage("https://example.com/2"),
            ]

        async def new_page(self):
            raise AssertionError("tab limit must be checked before opening a page")

    monkeypatch.setenv("AFFILIATE_MAX_BROWSER_TABS", "2")

    with pytest.raises(IntentPageError) as error:
        asyncio.run(ensure_affiliate_resource_pages([Context()]))

    assert error.value.category == "tab_limit_reached"
