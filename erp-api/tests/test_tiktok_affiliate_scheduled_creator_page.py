import asyncio
from dataclasses import replace

import pytest

from backend.app.services import tiktok_affiliate_intent_page as module
from backend.app.services.tiktok_affiliate_intent_page import IntentPageError
from tests.test_tiktok_affiliate_intent_page import _intent


class Page:
    def __init__(self, url: str, context=None) -> None:
        self.url = url
        self.context = context
        self.closed = False

    async def goto(self, url: str, **kwargs) -> None:
        self.url = url

    async def close(self) -> None:
        self.closed = True


class Context:
    def __init__(self, url: str) -> None:
        self.pages = [Page(url, self)]
        self.created = None

    async def new_page(self) -> Page:
        self.created = Page("about:blank", self)
        self.pages.append(self.created)
        return self.created


def test_scheduled_creator_uses_only_its_owned_page(monkeypatch) -> None:
    url = (
        "https://affiliate-us.tiktok.com/data/creator-analysis"
        "?shop_region=US&shop_id=platform-shop-1"
    )
    context = Context(url)
    selected = []

    async def no_security(_):
        return None

    async def prepare(page, _query):
        selected.append(page)

        async def trigger():
            return None

        return trigger

    monkeypatch.setattr(module, "page_security_failure", no_security)
    monkeypatch.setattr(module, "_prepare_trigger", prepare)
    intent = replace(_intent(), job_id="affiliate-schedule:20261008:test")
    result = asyncio.run(module.prepare_intent_page([context], intent))
    assert selected == [context.created]
    assert not context.pages[0].closed
    asyncio.run(result.cleanup())
    assert context.created.closed
    assert not context.pages[0].closed


def test_failed_scheduled_creator_closes_only_its_owned_page(monkeypatch) -> None:
    url = (
        "https://affiliate-us.tiktok.com/data/creator-analysis"
        "?shop_region=US&shop_id=platform-shop-1"
    )
    context = Context(url)

    async def no_security(_):
        return None

    async def fail(_page, _query):
        raise IntentPageError("window_not_settable")

    monkeypatch.setattr(module, "page_security_failure", no_security)
    monkeypatch.setattr(module, "_prepare_trigger", fail)
    intent = replace(_intent(), job_id="affiliate-schedule:20261008:test")
    with pytest.raises(IntentPageError, match="window_not_settable"):
        asyncio.run(module.prepare_intent_page([context], intent))
    assert context.created.closed
    assert not context.pages[0].closed
