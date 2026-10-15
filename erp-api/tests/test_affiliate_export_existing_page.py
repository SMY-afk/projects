"""Exact approved analytics-tab reuse never creates or closes a browser page."""

import importlib
from types import SimpleNamespace

import pytest

from scripts import send_local_affiliate_export as exporter

SHOP = "verified-platform-shop"
TARGET = "approved-video-target"
VIDEO_URL = f"https://affiliate-us.tiktok.com/insights/video-analysis?shop_id={SHOP}"


class Page:
    def __init__(self, url=VIDEO_URL, target=TARGET):
        self.url = url
        self.target = target
        self.closed = False

    async def goto(self, *_args, **_kwargs):
        pytest.fail("Reuse must not navigate the existing page")

    async def close(self):
        pytest.fail("Reuse must not close an existing page")


class Context:
    def __init__(self, pages):
        self.pages = pages
        self.detached = []

    async def new_page(self):
        pytest.fail("Approved reuse must never create a page")

    async def new_cdp_session(self, page):
        parent = self

        class Session:
            async def send(self, command):
                assert command == "Target.getTargetInfo"
                return {"targetInfo": {"targetId": page.target, "url": page.url}}

            async def detach(self):
                parent.detached.append(page.target)

        return Session()


@pytest.fixture
def page_controls(monkeypatch):
    module = importlib.import_module(exporter._prepare_owned_page.__module__)
    state = {"prepared": [], "cleanup": 0, "security": None}

    async def trigger(page, query):
        state["prepared"].append((page, query))

        async def run():
            return None

        async def cleanup():
            state["cleanup"] += 1

        run.cleanup = cleanup
        return run

    async def security(_page):
        return state["security"]

    monkeypatch.setattr(module, "_prepare_trigger", trigger)
    monkeypatch.setattr(module, "page_security_failure", security, raising=False)
    return state


@pytest.mark.asyncio
async def test_approved_video_target_is_reused_and_retained(page_controls):
    video = Page()
    sample = Page("https://affiliate-us.tiktok.com/samples/requests?shop_id=" + SHOP,
                  "sample-target")
    context = Context([sample, video])
    query = SimpleNamespace(resource=SimpleNamespace(value="videos"))
    prepared = await exporter._prepare_owned_page(
        context, query, SHOP, approved_page_target_id=TARGET)
    assert prepared.page is video
    assert context.pages == [sample, video]
    assert context.detached == [TARGET]
    await prepared.cleanup()
    assert page_controls["cleanup"] == 0
    assert page_controls["prepared"] == []
    assert not video.closed and not sample.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("pages", [
    [],
    [Page(target="different-target")],
    [Page("https://affiliate-us.tiktok.com/insights/video-analysis?shop_id=another")],
    [Page("https://affiliate-us.tiktok.com/samples/requests?shop_id=" + SHOP)],
    [Page("https://unapproved.invalid/insights/video-analysis?shop_id=" + SHOP)],
    [Page(), Page()],
])
async def test_missing_wrong_shop_sample_page_or_ambiguous_target_is_rejected(
    page_controls, pages,
):
    context = Context(pages)
    query = SimpleNamespace(resource=SimpleNamespace(value="videos"))
    with pytest.raises(RuntimeError, match="approved analytics"):
        await exporter._prepare_owned_page(
            context, query, SHOP, approved_page_target_id=TARGET)
    assert page_controls["prepared"] == []


@pytest.mark.asyncio
async def test_captcha_does_not_prepare_or_replace_target(page_controls):
    page_controls["security"] = ("blocked", "captcha")
    query = SimpleNamespace(resource=SimpleNamespace(value="videos"))
    with pytest.raises(RuntimeError, match="captcha"):
        await exporter._prepare_owned_page(
            Context([Page()]), query, SHOP, approved_page_target_id=TARGET)
    assert page_controls["prepared"] == []


@pytest.mark.asyncio
async def test_non_video_reuse_is_rejected(page_controls):
    query = SimpleNamespace(resource=SimpleNamespace(value="creators"))
    with pytest.raises(RuntimeError, match="video"):
        await exporter._prepare_owned_page(
            Context([Page()]), query, SHOP, approved_page_target_id=TARGET)
    assert page_controls["prepared"] == []


@pytest.mark.asyncio
async def test_original_default_still_owns_and_cleans_its_created_page(page_controls, monkeypatch):
    module = importlib.import_module(exporter._prepare_owned_page.__module__)
    original = Page("https://affiliate-us.tiktok.com/samples/requests?shop_id=" + SHOP)
    created = Page()
    context = Context([original])

    async def new_page():
        context.pages.append(created)
        return created

    async def goto(url, **kwargs):
        assert kwargs == {"wait_until": "domcontentloaded", "timeout": 30_000}
        created.url = url

    async def close(page):
        assert page is created
        page.closed = True

    monkeypatch.setattr(context, "new_page", new_page)
    monkeypatch.setattr(created, "goto", goto)
    monkeypatch.setattr(module, "_resource_page_url", lambda *_: VIDEO_URL)
    monkeypatch.setattr(module, "close_owned_page", close)
    query = SimpleNamespace(resource=SimpleNamespace(value="videos"))
    prepared = await exporter._prepare_owned_page(context, query, SHOP)
    assert prepared.page is created
    await prepared.cleanup()
    assert created.closed and not original.closed
    assert page_controls["cleanup"] == 0
    assert page_controls["prepared"] == []


@pytest.mark.asyncio
async def test_reuse_identity_change_is_rejected_without_closing_page(page_controls, monkeypatch):
    module = importlib.import_module(exporter._prepare_owned_page.__module__)
    async def redirected(page):
        page.url = "https://affiliate-us.tiktok.com/samples/requests?shop_id=" + SHOP

    monkeypatch.setattr(module, "page_security_failure", redirected)
    page = Page()
    query = SimpleNamespace(resource=SimpleNamespace(value="videos"))
    with pytest.raises(RuntimeError, match="changed shop or resource"):
        await exporter._prepare_owned_page(
            Context([page]), query, SHOP, approved_page_target_id=TARGET)
    assert page_controls["cleanup"] == 0
    assert page_controls["prepared"] == []
    assert not page.closed
