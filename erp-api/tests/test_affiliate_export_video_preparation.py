"""Original video exports must not wait for an unrelated list API template."""

from types import SimpleNamespace

import pytest

from scripts import affiliate_export_page as export_page

SHOP = "verified-shop"
TARGET = "approved-target"
URL = f"https://affiliate-us.tiktok.com/insights/video-analysis?shop_id={SHOP}"


class Page:
    def __init__(self, url=URL, redirect=None):
        self.url = url
        self.redirect = redirect
        self.closed = 0
        self.visits = []

    async def goto(self, url, **_kwargs):
        self.visits.append(url)
        self.url = self.redirect or url

    async def close(self):
        self.closed += 1


class Context:
    def __init__(self, page):
        self.page = page
        self.pages = [page]
        self.created = 0
        self.detached = 0

    async def new_page(self):
        self.created += 1
        return self.page

    async def new_cdp_session(self, page):
        parent = self

        class Session:
            async def send(self, _command):
                return {"targetInfo": {"targetId": TARGET, "url": page.url}}

            async def detach(self):
                parent.detached += 1

        return Session()


@pytest.fixture
def controls(monkeypatch):
    calls = {"list_template": 0, "security": None}

    async def trigger(_page, _query):
        calls["list_template"] += 1
        raise TimeoutError("Unrelated video list API did not respond")

    async def security(_page):
        return calls["security"]

    monkeypatch.setattr(export_page, "_prepare_trigger", trigger)
    monkeypatch.setattr(export_page, "page_security_failure", security)
    monkeypatch.setattr(export_page, "_resource_page_url", lambda *_args: URL)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize("reused", [False, True])
async def test_video_preparation_does_not_require_list_api(controls, reused):
    page = Page()
    context = Context(page)
    query = SimpleNamespace(resource=SimpleNamespace(value="videos"))
    prepared = await export_page.prepare_export_page(
        context, query, SHOP, approved_page_target_id=TARGET if reused else None
    )
    assert prepared.page is page and prepared.query is query
    assert controls["list_template"] == 0
    assert await prepared.trigger() is None
    await prepared.cleanup()
    assert page.closed == (0 if reused else 1)
    assert context.created == (0 if reused else 1)
    assert context.detached == int(reused)
    assert len(page.visits) == (0 if reused else 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("reused", [False, True])
async def test_video_captcha_is_rejected_without_list_request(controls, reused):
    controls["security"] = ("blocked", "captcha")
    page = Page()
    context = Context(page)
    query = SimpleNamespace(resource=SimpleNamespace(value="videos"))
    with pytest.raises(RuntimeError, match="captcha"):
        await export_page.prepare_export_page(
            context, query, SHOP, approved_page_target_id=TARGET if reused else None
        )
    assert controls["list_template"] == 0
    assert page.closed == (0 if reused else 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("redirect", [
    URL.replace("verified-shop", "another-shop"),
    URL.replace("affiliate-us.tiktok.com", "unapproved.invalid"),
    URL.replace("/insights/video-analysis", "/samples/requests"),
])
async def test_created_video_page_requires_approved_shop_host_and_path(controls, redirect):
    page = Page(redirect=redirect)
    query = SimpleNamespace(resource=SimpleNamespace(value="videos"))
    with pytest.raises(RuntimeError, match="identity"):
        await export_page.prepare_export_page(Context(page), query, SHOP)
    assert controls["list_template"] == 0 and page.closed == 1


@pytest.mark.asyncio
async def test_creator_preserves_trigger_preparation_and_cleanup(controls, monkeypatch):
    calls = []
    page = Page()
    query = SimpleNamespace(resource=SimpleNamespace(value="creators"))

    async def trigger():
        calls.append("trigger")

    async def cleanup():
        calls.append("cleanup")

    async def prepare(actual_page, actual_query):
        assert actual_page is page and actual_query is query
        calls.append("prepare")
        return trigger

    trigger.cleanup = cleanup
    monkeypatch.setattr(export_page, "_prepare_trigger", prepare)
    prepared = await export_page.prepare_export_page(Context(page), query, SHOP)
    await prepared.trigger()
    await prepared.cleanup()
    assert calls == ["prepare", "trigger", "cleanup"] and page.closed == 1
