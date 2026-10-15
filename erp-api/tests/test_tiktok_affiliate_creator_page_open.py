import asyncio

from backend.app.services.tiktok_affiliate_intent_page import (
    _ensure_creator_pages,
    _ensure_resource_pages,
    _resource_page_url,
)


class FakePage:
    def __init__(self, url: str = "about:blank") -> None:
        self.url = url
        self.goto_calls = []

    async def goto(self, url: str, **kwargs) -> None:
        self.goto_calls.append((url, kwargs))
        self.url = url


class FakeContext:
    def __init__(self, pages) -> None:
        self.pages = pages
        self.created = []

    async def new_page(self) -> FakePage:
        page = FakePage()
        self.created.append(page)
        self.pages.append(page)
        return page


def test_daemon_opens_creator_page_inside_each_missing_browser_context() -> None:
    async def run():
        existing = FakePage(
            "https://affiliate.tiktokshopglobalselling.com/data/creator-analysis"
        )
        first = FakeContext([existing])
        second = FakeContext([])
        pages = await _ensure_creator_pages(
            [first, second],
            [existing],
            "/data/creator-analysis",
        )
        return first, second, pages

    first, second, pages = asyncio.run(run())

    assert first.created == []
    assert len(second.created) == 1
    assert second.created[0].goto_calls == [
        (
            "https://affiliate.tiktokshopglobalselling.com/data/creator-analysis",
            {"wait_until": "domcontentloaded", "timeout": 30_000},
        )
    ]
    assert pages == [first.pages[0], second.created[0]]


def test_daemon_opens_video_page_when_the_resource_tab_is_missing() -> None:
    async def run():
        context = FakeContext([])
        pages = await _ensure_resource_pages(
            [context],
            [],
            "/affiliate/assets/video-analysis",
            "videos",
        )
        return context, pages

    context, pages = asyncio.run(run())

    assert len(context.created) == 1
    assert context.created[0].goto_calls == [
        (
            "https://affiliate.tiktokshopglobalselling.com/affiliate/assets/video-analysis",
            {"wait_until": "domcontentloaded", "timeout": 30_000},
        )
    ]
    assert pages == [context.created[0]]


def test_us_browser_opens_shop_bound_creator_page() -> None:
    context = FakeContext(
        [
            FakePage(
                "https://affiliate-us.tiktok.com/affiliate/sample/sample-request"
                "?shop_region=US&shop_id=platform-shop-1"
            )
        ]
    )

    assert _resource_page_url(
        [context], "creators", "platform-shop-1"
    ) == (
        "https://affiliate-us.tiktok.com/data/creator-analysis"
        "?shop_region=US&shop_id=platform-shop-1"
    )
