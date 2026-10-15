import asyncio

import pytest

from backend.app.services import tiktok_sample_creator_details_collector as module
from backend.app.services.tiktok_sample_creator_details_collector import (
    CAPTCHA_SELECTOR,
    SEARCH_SELECTOR,
    SampleCreatorDetailsTarget,
    TikTokSampleCreatorDetailsCollector,
    creator_details_identity_matches,
    ensure_no_captcha,
    reload_creator_details_page,
)


def test_creator_search_selector_supports_english_and_chinese_pages() -> None:
    assert 'placeholder="Search creator name"' in SEARCH_SELECTOR
    assert 'placeholder="\u641c\u7d22\u8fbe\u4eba\u6635\u79f0"' in SEARCH_SELECTOR


def test_captcha_guard_blocks_creator_interaction() -> None:
    class Locator:
        async def is_visible(self) -> bool:
            return True

    class Page:
        def locator(self, selector):
            assert selector == CAPTCHA_SELECTOR
            return Locator()

    with pytest.raises(RuntimeError, match="captcha"):
        asyncio.run(ensure_no_captcha(Page()))


def test_creator_details_identity_requires_same_sample_shop_and_username() -> None:
    url = (
        "https://affiliate-us.tiktok.com/affiliate/creator/detail"
        "?cid=detail-id&cname=%40CreatorOne&shop_id=shop-one"
    )
    assert creator_details_identity_matches(url, "shop-one", "creatorone") is True
    assert creator_details_identity_matches(url, "shop-two", "creatorone") is False
    assert creator_details_identity_matches(url, "shop-one", "creator-two") is False
    assert (
        creator_details_identity_matches(
            "https://affiliate-us.tiktok.com/data/creator-analysis"
            "?cname=CreatorOne&shop_id=shop-one",
            "shop-one",
            "creatorone",
        )
        is False
    )


def test_reload_creator_details_page_revalidates_identity() -> None:
    class Page:
        url = (
            "https://affiliate-us.tiktok.com/affiliate/creator/detail"
            "?cname=CreatorOne&shop_id=shop-one"
        )
        reloaded = False

        async def reload(self, **kwargs) -> None:
            assert kwargs == {"wait_until": "domcontentloaded", "timeout": 60_000}
            self.reloaded = True

    page = Page()

    asyncio.run(reload_creator_details_page(page, "shop-one", "creatorone"))

    assert page.reloaded is True


def test_reload_creator_details_page_rejects_changed_identity() -> None:
    class Page:
        url = (
            "https://affiliate-us.tiktok.com/affiliate/creator/detail"
            "?cname=CreatorOne&shop_id=shop-one"
        )

        async def reload(self, **_kwargs) -> None:
            self.url = (
                "https://affiliate-us.tiktok.com/affiliate/creator/detail"
                "?cname=OtherCreator&shop_id=shop-one"
            )

    with pytest.raises(RuntimeError, match="identity does not match"):
        asyncio.run(reload_creator_details_page(Page(), "shop-one", "creatorone"))


def test_capture_removes_response_listener_when_page_preparation_fails(
    monkeypatch,
) -> None:
    class Capture:
        stopped = False

        def __init__(self, *_args) -> None:
            pass

        def schedule_response(self, _response) -> None:
            pass

        async def stop(self) -> None:
            self.stopped = True

    class Search:
        async def wait_for(self, **_kwargs) -> None:
            raise RuntimeError("page unavailable")

        async def fill(self, _value) -> None:
            pass

        async def press(self, _key) -> None:
            pass

    class Context:
        def __init__(self) -> None:
            self.handler = None
            self.removed = None

        def on(self, event, handler) -> None:
            self.handler = (event, handler)

        def remove_listener(self, event, handler) -> None:
            self.removed = (event, handler)

    context = Context()
    page = type(
        "Page",
        (),
        {"context": context, "locator": lambda _self, _selector: Search()},
    )()
    monkeypatch.setattr(module, "_sample_request_page", lambda *_args: page)
    monkeypatch.setattr(module, "TikTokAffiliateCreatorSummaryCapture", Capture)
    collector = TikTokSampleCreatorDetailsCollector(
        module.UUID(int=1),
        module.UUID(int=2),
        "shop-one",
        object(),
    )

    with pytest.raises(RuntimeError, match="page unavailable"):
        asyncio.run(
            collector.capture(
                [],
                [SampleCreatorDetailsTarget("creator", frozenset())],
            )
        )

    assert context.handler is not None
    assert context.removed == context.handler


def test_capture_rejects_profile_when_required_sources_were_not_persisted(
    monkeypatch,
) -> None:
    class Capture:
        def __init__(self, *_args) -> None:
            pass

        def schedule_response(self, _response) -> None:
            pass

        async def wait_for_pending(self) -> None:
            pass

        def has_complete_profile(self, _shop_id, _username) -> bool:
            return False

        async def stop(self) -> None:
            pass

    class Locator:
        def __init__(self, kind: str) -> None:
            self.kind = kind

        async def wait_for(self, **_kwargs) -> None:
            pass

        async def fill(self, _value) -> None:
            pass

        async def press(self, _key) -> None:
            pass

        def filter(self, **_kwargs):
            return self

        def locator(self, _selector):
            return self

        @property
        def first(self):
            return self

        async def count(self) -> int:
            return 1

        async def click(self, **_kwargs) -> None:
            pass

        async def is_visible(self) -> bool:
            return False

    class DetailPage:
        url = (
            "https://affiliate-us.tiktok.com/affiliate/creator/detail"
            "?cname=creator&shop_id=shop-one"
        )

        async def wait_for_load_state(self, *_args, **_kwargs) -> None:
            pass

        async def reload(self, **_kwargs) -> None:
            pass

        async def wait_for_timeout(self, _timeout) -> None:
            pass

        async def close(self) -> None:
            pass

    class PageInfo:
        def __init__(self) -> None:
            async def detail_page():
                return DetailPage()

            self.value = detail_page()

    class ExpectPage:
        async def __aenter__(self):
            return PageInfo()

        async def __aexit__(self, *_args) -> None:
            pass

    class Context:
        def on(self, _event, _handler) -> None:
            pass

        def remove_listener(self, _event, _handler) -> None:
            pass

        def expect_page(self, **_kwargs):
            return ExpectPage()

    class SamplePage:
        context = Context()

        def locator(self, selector):
            if selector == "tr":
                return Locator("rows")
            return Locator("search")

    monkeypatch.setattr(module, "_sample_request_page", lambda *_args: SamplePage())
    monkeypatch.setattr(module, "TikTokAffiliateCreatorSummaryCapture", Capture)
    collector = TikTokSampleCreatorDetailsCollector(
        module.UUID(int=1),
        module.UUID(int=2),
        "shop-one",
        object(),
    )

    with pytest.raises(RuntimeError, match="incomplete"):
        asyncio.run(
            collector.capture(
                [],
                [SampleCreatorDetailsTarget("creator", frozenset())],
            )
        )


def test_capture_supports_creator_details_opening_in_same_tab(monkeypatch) -> None:
    class Capture:
        def __init__(self, *_args) -> None:
            pass

        def schedule_response(self, _response) -> None:
            pass

        async def wait_for_pending(self) -> None:
            pass

        def has_complete_profile(self, _shop_id, _username) -> bool:
            return True

        async def stop(self) -> None:
            pass

    class Locator:
        def __init__(self, page, kind: str) -> None:
            self.page = page
            self.kind = kind

        async def wait_for(self, **_kwargs) -> None:
            pass

        async def fill(self, _value) -> None:
            pass

        async def press(self, _key) -> None:
            pass

        def filter(self, **_kwargs):
            return self

        def locator(self, _selector):
            return Locator(self.page, "avatar")

        @property
        def first(self):
            return self

        async def count(self) -> int:
            return 1

        async def click(self, **_kwargs) -> None:
            if self.kind == "avatar":
                self.page.url = (
                    "https://affiliate-us.tiktok.com/affiliate/creator/detail"
                    "?cname=creator&shop_id=shop-one"
                )

        async def is_visible(self) -> bool:
            return False

    class PageInfo:
        value = None

    class ExpectPage:
        async def __aenter__(self):
            return PageInfo()

        async def __aexit__(self, *_args) -> None:
            raise module.PlaywrightTimeoutError("creator opened in same tab")

    class Context:
        def on(self, _event, _handler) -> None:
            pass

        def remove_listener(self, _event, _handler) -> None:
            pass

        def expect_page(self, **_kwargs):
            return ExpectPage()

    class SamplePage:
        context = Context()
        url = (
            "https://affiliate-us.tiktok.com/affiliate/sample/sample-request"
            "?shop_id=shop-one"
        )
        restored = 0
        closed = False

        def locator(self, selector):
            return Locator(self, "rows" if selector == "tr" else "search")

        async def wait_for_load_state(self, *_args, **_kwargs) -> None:
            pass

        async def reload(self, **_kwargs) -> None:
            pass

        async def wait_for_timeout(self, _timeout) -> None:
            pass

        async def goto(self, url, **_kwargs) -> None:
            self.url = url
            self.restored += 1

        async def close(self) -> None:
            self.closed = True

    page = SamplePage()
    monkeypatch.setattr(module, "_sample_request_page", lambda *_args: page)
    monkeypatch.setattr(module, "TikTokAffiliateCreatorSummaryCapture", Capture)
    collector = TikTokSampleCreatorDetailsCollector(
        module.UUID(int=1),
        module.UUID(int=2),
        "shop-one",
        object(),
    )

    assert (
        asyncio.run(
            collector.capture(
                [],
                [SampleCreatorDetailsTarget("creator", frozenset())],
            )
        )
        == 1
    )
    assert page.restored == 1
    assert page.closed is False


def test_open_creator_details_supports_reused_existing_tab() -> None:
    class Page:
        def __init__(self, url: str) -> None:
            self.url = url

    sample_page = Page(
        "https://affiliate-us.tiktok.com/affiliate/sample/sample-request"
        "?shop_id=shop-one"
    )
    existing_page = Page(
        "https://affiliate-us.tiktok.com/affiliate/creator/detail"
        "?cname=creator&shop_id=shop-one"
    )

    class ExpectPage:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *_args) -> None:
            raise module.PlaywrightTimeoutError("creator reused an existing tab")

    class Context:
        def __init__(self) -> None:
            self.pages = [sample_page, existing_page]

        def expect_page(self, **_kwargs):
            return ExpectPage()

    class Avatar:
        async def click(self, **_kwargs) -> None:
            pass

    page, mode = asyncio.run(
        module.open_creator_details_page(
            Context(),
            sample_page,
            Avatar(),
            "shop-one",
            "creator",
        )
    )

    assert page is existing_page
    assert mode == "existing"


def test_open_creator_details_falls_back_to_owned_direct_tab() -> None:
    class Page:
        def __init__(self, url: str) -> None:
            self.url = url
            self.visited = None

        async def goto(self, url, **kwargs) -> None:
            self.url = url
            self.visited = kwargs

    sample_page = Page(
        "https://affiliate-us.tiktok.com/affiliate/sample/sample-request"
        "?shop_id=shop-one"
    )
    owned_page = Page("about:blank")

    class ExpectPage:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *_args) -> None:
            raise module.PlaywrightTimeoutError("creator did not open automatically")

    class Context:
        def __init__(self) -> None:
            self.pages = [sample_page]

        def expect_page(self, **_kwargs):
            return ExpectPage()

        async def new_page(self):
            return owned_page

    class Avatar:
        async def click(self, **_kwargs) -> None:
            pass

    page, mode = asyncio.run(
        module.open_creator_details_page(
            Context(),
            sample_page,
            Avatar(),
            "shop-one",
            "creator",
        )
    )

    assert page is owned_page
    assert mode == "popup"
    assert module.creator_details_identity_matches(
        owned_page.url,
        "shop-one",
        "creator",
    )
    assert owned_page.visited == {
        "wait_until": "domcontentloaded",
        "timeout": 60_000,
    }


def test_open_creator_details_force_clicks_verified_avatar() -> None:
    class DetailPage:
        pass

    detail_page = DetailPage()

    class PageInfo:
        async def value(self):
            return detail_page

    class ExpectPage:
        async def __aenter__(self):
            info = PageInfo()
            info.value = info.value()
            return info

        async def __aexit__(self, *_args) -> None:
            pass

    class Context:
        def expect_page(self, **_kwargs):
            return ExpectPage()

    class Avatar:
        click_kwargs = None

        async def click(self, **kwargs) -> None:
            self.click_kwargs = kwargs

    avatar = Avatar()
    page, mode = asyncio.run(
        module.open_creator_details_page(
            Context(),
            object(),
            avatar,
            "shop-one",
            "creator",
        )
    )

    assert page is detail_page
    assert mode == "popup"
    assert avatar.click_kwargs == {"timeout": 15_000, "force": True}
