"""Export picker evidence can advance beyond unrelated conservative API modules."""

import asyncio
from datetime import date
from urllib.parse import parse_qs, urlsplit

import pytest

from backend.app.services import tiktok_affiliate_available_date as availability
from backend.app.services import tiktok_affiliate_export_picker_date as export_picker


class EmptyLocator:
    async def count(self):
        return 0


class Page:
    def __init__(self, url, *, redirect=None, navigation_error=False):
        self.url = url
        self.redirect = redirect
        self.navigation_error = navigation_error
        self.closed = 0
        self.visits = []

    async def goto(self, url, **_kwargs):
        self.visits.append(url)
        if self.navigation_error:
            raise RuntimeError("Navigation failed")
        self.url = self.redirect or url

    async def close(self):
        self.closed += 1

    def locator(self, _selector):
        return EmptyLocator()


class Context:
    def __init__(self, host, *, redirect=None, navigation_error=False):
        self.existing = Page(
            f"https://{host}/data/creator-analysis?shop_id=123&shop_region=US"
        )
        self.pages = [self.existing]
        self.temporary = Page(
            "about:blank", redirect=redirect, navigation_error=navigation_error
        )
        self.created = 0

    async def new_page(self):
        self.created += 1
        return self.temporary


@pytest.mark.parametrize(
    "host", ["affiliate.tiktokshopglobalselling.com", "affiliate-us.tiktok.com"]
)
def test_enabled_export_picker_advances_video_date_beyond_api_min(monkeypatch, host):
    context = Context(host)
    api_calls = []

    async def conservative_api(*_args):
        api_calls.append(True)
        return date(2026, 10, 11)

    async def picker(page, resource, **kwargs):
        assert page is context.temporary
        assert resource == "videos" and kwargs == {"refresh": False}
        split = urlsplit(page.url)
        assert split.netloc == host
        assert split.path == "/affiliate/assets/video-analysis"
        assert parse_qs(split.query) == {"shop_id": ["123"], "shop_region": ["US"]}
        return date(2026, 10, 12)

    monkeypatch.setattr(availability, "detect_video_api_latest_day", conservative_api)
    monkeypatch.setattr(availability, "_detect_page_date", picker)

    assert asyncio.run(availability._detect_resource_date([context], "videos")) == date(
        2026, 10, 12
    )
    assert api_calls == []
    assert context.created == context.temporary.closed == 1
    assert context.existing.visits == [] and context.existing.closed == 0


@pytest.mark.parametrize("failure", ["unavailable", "navigation", "timeout", "stalled"])
def test_unavailable_export_picker_falls_back_to_conservative_api(monkeypatch, failure):
    context = Context("affiliate.tiktokshopglobalselling.com",
                      navigation_error=failure == "navigation")
    api_calls = []

    async def conservative_api(source, page_url):
        assert source is context
        assert urlsplit(page_url).path == "/insights/video-analysis"
        api_calls.append(True)
        return date(2026, 10, 11)

    async def picker(*_args, **_kwargs):
        if failure == "timeout":
            raise TimeoutError("Picker is not ready")
        if failure == "stalled":
            await asyncio.Event().wait()

    monkeypatch.setattr(export_picker, "EXPORT_PICKER_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(availability, "detect_video_api_latest_day", conservative_api)
    monkeypatch.setattr(availability, "_detect_page_date", picker)
    assert asyncio.run(availability._detect_resource_date([context], "videos")) == date(
        2026, 10, 11
    )
    assert api_calls == [True]
    assert context.created == context.temporary.closed == 1
    assert context.existing.closed == 0


@pytest.mark.parametrize("redirect", [
    "https://affiliate.tiktokshopglobalselling.com/affiliate/assets/video-analysis?shop_id=456",
    "https://affiliate-us.tiktok.com/affiliate/assets/video-analysis?shop_id=123",
    "https://example.invalid/affiliate/assets/video-analysis?shop_id=123",
    "https://affiliate.tiktokshopglobalselling.com/login?shop_id=123",
    "https://affiliate.tiktokshopglobalselling.com/captcha?shop_id=123",
    "https://affiliate.tiktokshopglobalselling.com/affiliate/assets/video-analysis?shop_id=123&shop_id=456",
])
def test_redirected_export_picker_cannot_supply_another_shop_date(monkeypatch, redirect):
    context = Context("affiliate.tiktokshopglobalselling.com", redirect=redirect)
    picker_calls = []

    async def conservative_api(*_args):
        return date(2026, 10, 11)

    async def picker(*_args, **_kwargs):
        picker_calls.append(True)
        return date(2026, 10, 12)

    monkeypatch.setattr(availability, "detect_video_api_latest_day", conservative_api)
    monkeypatch.setattr(availability, "_detect_page_date", picker)
    assert asyncio.run(availability._detect_resource_date([context], "videos")) == date(
        2026, 10, 11
    )
    assert context.created == context.temporary.closed == 1
    assert context.existing.closed == 0
    assert picker_calls == []


def test_visible_captcha_blocks_picker_evidence(monkeypatch):
    context = Context("affiliate.tiktokshopglobalselling.com")
    picker_calls = []

    async def insecure(_page):
        return "session_required", "captcha"

    async def conservative_api(*_args):
        return date(2026, 10, 11)

    async def picker(*_args, **_kwargs):
        picker_calls.append(True)
        return date(2026, 10, 12)

    monkeypatch.setattr(export_picker, "page_security_failure", insecure)
    monkeypatch.setattr(availability, "detect_video_api_latest_day", conservative_api)
    monkeypatch.setattr(availability, "_detect_page_date", picker)
    assert asyncio.run(availability._detect_resource_date([context], "videos")) == date(
        2026, 10, 11
    )
    assert picker_calls == []
    assert context.temporary.closed == 1 and context.existing.closed == 0


def test_page_identity_is_rechecked_after_picker_read(monkeypatch):
    context = Context("affiliate.tiktokshopglobalselling.com")

    async def conservative_api(*_args):
        return date(2026, 10, 11)

    async def picker(page, *_args, **_kwargs):
        page.url = page.url.replace("shop_id=123", "shop_id=456")
        return date(2026, 10, 12)

    monkeypatch.setattr(availability, "detect_video_api_latest_day", conservative_api)
    monkeypatch.setattr(availability, "_detect_page_date", picker)
    assert asyncio.run(availability._detect_resource_date([context], "videos")) == date(
        2026, 10, 11
    )
    assert context.temporary.closed == 1 and context.existing.closed == 0
