"""One-time video targets survive failures without creating replacement tabs."""

import json
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from scripts import prepare_dedicated_affiliate_video_page as dedicated


class Page:
    def __init__(self):
        self.url = "about:blank"
        self.target = "new-target"
        self.markers = []

    async def goto(self, url, **_):
        self.url = url

    async def evaluate(self, expression, marker):
        self.markers.append((expression, marker))

    async def close(self):
        pytest.fail("Dedicated video tabs must be retained")


class Context:
    def __init__(self):
        self.pages = []
        self.created = 0
        self.creation_error = False

    async def new_page(self):
        self.created += 1
        if self.creation_error:
            raise TimeoutError("Unknown creation outcome")
        page = Page()
        self.pages.append(page)
        return page

    async def new_cdp_session(self, page):
        class Session:
            async def send(self, _):
                return {"targetInfo": {"targetId": page.target, "url": page.url}}

            async def detach(self):
                return None

        return Session()


@pytest.fixture
def settings(monkeypatch, tmp_path):
    state = {"security": None}

    async def security(_):
        return state["security"]

    monkeypatch.setattr(dedicated, "page_security_failure", security)
    state["path"] = tmp_path / "registry.json"
    state["binding"] = {"shop_id": "erp-shop", "environment_id": "env-id",
                        "cdp_url": "http://127.0.0.1:12345"}
    return state


@pytest.mark.asyncio
async def test_create_once_then_reuse_the_registered_exact_target(settings):
    context = Context()
    args = (context, "platform", "cross-border-3", settings["path"], settings["binding"])
    first = await dedicated.prepare_registered_video_page(*args)
    second = await dedicated.prepare_registered_video_page(*args)
    assert first == second == "new-target"
    assert context.created == 1
    record = json.loads(settings["path"].read_text(encoding="utf-8"))["cross-border-3"]
    assert record["target_id"] == "new-target" and record["state"] == "ready"
    assert context.pages[0].markers


@pytest.mark.asyncio
async def test_unknown_creation_outcome_is_not_retried(settings):
    context = Context()
    context.creation_error = True
    args = (context, "platform", "cross-border-3", settings["path"], settings["binding"])
    with pytest.raises(TimeoutError):
        await dedicated.prepare_registered_video_page(*args)
    with pytest.raises(RuntimeError, match="outcome unknown"):
        await dedicated.prepare_registered_video_page(*args)
    assert context.created == 1


@pytest.mark.asyncio
async def test_captcha_keeps_created_target_and_stops(settings):
    settings["security"] = ("blocked", "captcha")
    context = Context()
    with pytest.raises(RuntimeError, match="captcha"):
        await dedicated.prepare_registered_video_page(
            context, "platform", "cross-border-3", settings["path"], settings["binding"])
    record = json.loads(settings["path"].read_text(encoding="utf-8"))["cross-border-3"]
    assert record["target_id"] == "new-target"
    assert context.created == len(context.pages) == 1


@pytest.mark.asyncio
async def test_mismatched_registry_binding_never_creates_a_page(settings):
    settings["path"].write_text(json.dumps({"cross-border-3": {
        **settings["binding"], "environment_id": "wrong-env", "target_id": "existing"}}))
    context = Context()
    with pytest.raises(RuntimeError, match="binding"):
        await dedicated.prepare_registered_video_page(
            context, "platform", "cross-border-3", settings["path"], settings["binding"])
    assert context.created == 0


@pytest.mark.asyncio
async def test_prepare_and_export_share_one_priority_lease(settings, monkeypatch):
    calls = []
    context = Context()
    source = Page()
    source.url = "https://affiliate-us.tiktok.com/samples/requests?shop_id=platform"
    context.pages.append(source)
    window = {"resource": "videos", "start": "2026-10-10", "end": "2026-10-11"}
    plans = iter([{"shops": [{"shop_id": "erp-shop", "health_ready": True,
                              "sample_released": True, "missing": [window]}]},
                  {"shops": [{"shop_id": "erp-shop", "missing": []}]}])

    class Playwright:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *_):
            return None

    async def discover(**_):
        return "http://127.0.0.1:12345"

    async def identity(_):
        return frozenset({"platform"})

    async def attached(*_):
        return SimpleNamespace(contexts=[context])

    async def priority(label, factory):
        calls.append(("priority", label))
        await factory()

    async def execute(args, shop, actual_window, label):
        calls.append(("export", label, args.approved_page_target_id))
        assert shop["shop_id"] == "erp-shop" and actual_window == window
        return "stored"

    def lease(label):
        calls.append(("lease", label))
        return nullcontext()

    monkeypatch.setattr(dedicated, "SHOPS", {"cross-border-3": ("erp-shop", "env-id", "platform")})
    monkeypatch.setattr(dedicated, "fetch_plan", lambda: next(plans))
    monkeypatch.setattr(dedicated, "async_playwright", Playwright)
    monkeypatch.setattr(dedicated, "discover_hubstudio_cdp_url", discover)
    monkeypatch.setattr(dedicated, "read_cdp_platform_shop_ids", identity)
    monkeypatch.setattr(dedicated, "assert_erp_hubstudio_cdp_url", lambda _: None)
    monkeypatch.setattr(dedicated, "connect_attached_hubstudio_browser", attached)
    monkeypatch.setattr(dedicated, "browser_work", lease)
    monkeypatch.setattr(dedicated, "run_secondary", priority)
    monkeypatch.setattr(dedicated, "execute_window", execute)
    await dedicated.run(SimpleNamespace(shop_label="cross-border-3",
                                       registry=settings["path"], recover_missing=True))
    assert calls == [("lease", "cross-border-3"), ("priority", "cross-border-3"),
                     ("export", "cross-border-3", "new-target")]
    assert context.created == 1 and context.pages[0] is source
