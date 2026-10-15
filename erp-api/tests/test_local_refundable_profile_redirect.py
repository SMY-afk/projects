"""Do not keep probing creators on an official local affiliate redirect."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.app.services import refundable_creator_profile_capture as capture

SHOP = "9136806951995371293"
ORIGINAL = f"https://affiliate-us.tiktok.com/affiliate/sample/sample-request?shop_id={SHOP}&shop_region=US"
LANDING = "https://seller-us.tiktok.com/affiliate/landing"


class RedirectPage:
    def __init__(self):
        self.url = ORIGINAL
        self.navigations = []

    def on(self, *_args):
        pass

    def remove_listener(self, *_args):
        pass

    async def goto(self, url, **_kwargs):
        self.navigations.append(url)
        self.url = ORIGINAL if url == ORIGINAL else LANDING


@pytest.mark.asyncio
async def test_local_redirect_stops_further_profiles_and_restores_verified_page(monkeypatch):
    page = RedirectPage()
    monkeypatch.setattr(capture, "page_security_failure", AsyncMock(return_value=None))
    monkeypatch.setattr(capture.asyncio, "sleep", AsyncMock())

    async def restore(page, _endpoint, _platform, _host, original_url):
        await page.goto(original_url)
        return True

    monkeypatch.setattr(capture, "restore_local_owned_redirect", restore, raising=False)
    items = [{"creator": {"username": str(index), "creator_open_id": str(index)}}
             for index in range(3)]
    cache = SimpleNamespace(load=lambda *_args: None, save=lambda *_args: False)
    profiles = await capture.capture_refundable_profiles(
        "endpoint", SHOP, items, host="affiliate-us.tiktok.com",
        reuse_page=page, profile_cache=cache,
    )
    assert page.url == ORIGINAL
    assert len(page.navigations) == 2  # One failed detail, one verified restore.
    assert profiles == {"0": [], "1": [], "2": []}
