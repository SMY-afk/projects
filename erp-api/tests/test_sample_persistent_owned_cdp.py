"""Persistent collection must reuse only targets it created in this browser."""

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from backend.app.services import sample_owned_cdp as module
from backend.app.services.sample_persistent_target import persistent_sample_key


@pytest.fixture
def browser(monkeypatch):
    state = SimpleNamespace(
        targets=[], created=[], closed=[], browser="ws://browser/one"
    )

    class Client:
        async def get(self, url):
            payload = (
                {"webSocketDebuggerUrl": state.browser}
                if url.endswith("/json/version")
                else state.targets
            )
            return SimpleNamespace(json=lambda: payload, raise_for_status=lambda: None)

    @asynccontextmanager
    async def client(**_kwargs):
        yield Client()

    @asynccontextmanager
    async def connect(*_args, **_kwargs):
        yield object()

    @asynccontextmanager
    async def serve(*_args, **_kwargs):
        yield SimpleNamespace(
            sockets=[SimpleNamespace(getsockname=lambda: ("127.0.0.1", 1234))]
        )

    async def command(_socket, _request_id, method, params):
        if method == "Target.createTarget":
            target_id = f"owned-{len(state.created) + 1}"
            state.created.append(target_id)
            state.targets.append(
                {"id": target_id, "type": "page", "url": "about:blank"}
            )
            return {"targetId": target_id}
        if method == "Target.closeTarget":
            state.closed.append(params["targetId"])
            state.targets[:] = [
                t for t in state.targets if t["id"] != params["targetId"]
            ]
            return {}
        raise AssertionError(method)

    monkeypatch.setattr(module.httpx, "AsyncClient", client)
    monkeypatch.setattr(module.websockets, "connect", connect)
    monkeypatch.setattr(module.websockets, "serve", serve)
    monkeypatch.setattr(module, "_command", command)
    return state


@pytest.mark.asyncio
async def test_two_cycles_keep_the_same_owned_target(browser, tmp_path):
    for _ in range(2):
        async with module.owned_sample_cdp(
            "http://127.0.0.1:61000",
            persistent_key=("shop-7", "free"),
            registry_root=tmp_path,
        ):
            pass
    assert browser.created == ["owned-1"]
    assert browser.closed == []


@pytest.mark.asyncio
async def test_captcha_keeps_owned_page_for_manual_verification(browser, tmp_path):
    with pytest.raises(RuntimeError, match="captcha"):
        async with module.owned_sample_cdp(
            "http://127.0.0.1:61000",
            persistent_key=("shop-7", "free"),
            registry_root=tmp_path,
        ):
            browser.targets[0]["url"] = (
                "https://affiliate.tiktokshopglobalselling.com/captcha"
            )
            raise RuntimeError("captcha")
    assert browser.created == ["owned-1"]
    assert browser.closed == []


@pytest.mark.asyncio
async def test_closed_target_is_recreated_without_adopting_external_page(
    browser, tmp_path
):
    kwargs = {"persistent_key": ("shop-7", "free"), "registry_root": tmp_path}
    async with module.owned_sample_cdp("http://127.0.0.1:61000", **kwargs):
        pass
    browser.targets[:] = [{"id": "external", "type": "page", "url": "about:blank"}]
    async with module.owned_sample_cdp("http://127.0.0.1:61000", **kwargs):
        pass
    assert browser.created == ["owned-1", "owned-2"]
    assert browser.closed == []


@pytest.mark.asyncio
async def test_browser_restart_invalidates_old_target_ownership(browser, tmp_path):
    kwargs = {"persistent_key": ("shop-7", "free"), "registry_root": tmp_path}
    async with module.owned_sample_cdp("http://127.0.0.1:61000", **kwargs):
        pass
    browser.browser = "ws://browser/two"
    async with module.owned_sample_cdp("http://127.0.0.1:61000", **kwargs):
        pass
    assert browser.created == ["owned-1", "owned-2"]
    assert browser.closed == []


@pytest.mark.asyncio
async def test_scratch_collection_still_closes_only_its_created_page(browser):
    async with module.owned_sample_cdp("http://127.0.0.1:61000"):
        pass
    assert browser.created == ["owned-1"]
    assert browser.closed == ["owned-1"]


@pytest.mark.asyncio
async def test_page_ceiling_blocks_creation_but_allows_owned_reuse(browser, tmp_path):
    kwargs = {"persistent_key": ("shop-7", "free"), "registry_root": tmp_path}
    async with module.owned_sample_cdp("http://127.0.0.1:61000", **kwargs):
        pass
    browser.targets.extend(
        {"id": f"external-{i}", "type": "page", "url": "about:blank"} for i in range(7)
    )
    async with module.owned_sample_cdp("http://127.0.0.1:61000", **kwargs):
        pass
    with pytest.raises(RuntimeError, match="tab_limit_reached"):
        async with module.owned_sample_cdp(
            "http://127.0.0.1:61000",
            persistent_key=("shop-7", "refundable"),
            registry_root=tmp_path,
        ):
            pass
    assert browser.created == ["owned-1"]


@pytest.mark.asyncio
async def test_free_and_paid_share_only_the_approved_owned_target(browser, tmp_path):
    for purpose in ("free", "refundable", "free", "refundable"):
        async with module.owned_sample_cdp(
            "http://127.0.0.1:61000",
            persistent_key=persistent_sample_key("9121478993551097445", purpose),
            registry_root=tmp_path,
        ):
            pass
    assert browser.created == ["owned-1"]
    assert browser.closed == []


@pytest.mark.asyncio
async def test_owned_target_navigated_to_another_shop_is_rejected(browser, tmp_path):
    kwargs = {"persistent_key": ("shop-7", "free"), "registry_root": tmp_path}
    async with module.owned_sample_cdp("http://127.0.0.1:61000", **kwargs):
        pass
    browser.targets[0]["url"] = (
        "https://affiliate.tiktokshopglobalselling.com/affiliate/sample/sample-request?shop_id=another"
    )
    with pytest.raises(RuntimeError, match="owned_page_shop_changed"):
        async with module.owned_sample_cdp("http://127.0.0.1:61000", **kwargs):
            pass
    assert browser.created == ["owned-1"]
    assert browser.closed == []


@pytest.mark.asyncio
async def test_invalid_registry_fails_closed_without_creating_a_tab(browser, tmp_path):
    kwargs = {"persistent_key": ("shop-7", "free"), "registry_root": tmp_path}
    async with module.owned_sample_cdp("http://127.0.0.1:61000", **kwargs):
        pass
    next(tmp_path.glob("*.json")).write_text("broken", encoding="utf-8")
    with pytest.raises(RuntimeError, match="owned_page_registry_invalid"):
        async with module.owned_sample_cdp("http://127.0.0.1:61000", **kwargs):
            pass
    assert browser.created == ["owned-1"]


@pytest.mark.asyncio
async def test_only_owned_errorpage_is_closed(browser, tmp_path):
    kwargs = {"persistent_key": ("shop-7", "free"), "registry_root": tmp_path}
    external = {
        "id": "external",
        "type": "page",
        "url": "https://affiliate.tiktokshopglobalselling.com/errorpage",
    }
    browser.targets.append(external)
    async with module.owned_sample_cdp("http://127.0.0.1:61000", **kwargs):
        browser.targets[-1]["url"] = (
            "https://affiliate.tiktokshopglobalselling.com/errorpage"
        )
    assert browser.closed == ["owned-1"]
    assert browser.targets == [external]
    async with module.owned_sample_cdp("http://127.0.0.1:61000", **kwargs):
        pass
    assert browser.created == ["owned-1", "owned-2"]


def test_persistent_reuse_rollout_covers_four_cross_border_shops():
    assert persistent_sample_key("9121478993551097445") == (
        "9121478993551097445",
        "free",
    )
    assert persistent_sample_key("9121478993551097445", "refundable")[1] == "free"
    assert persistent_sample_key("9622543325839925006") == ("9622543325839925006", "free")
    assert persistent_sample_key("9472478445887813622") == ("9472478445887813622", "free")


@pytest.mark.asyncio
async def test_approved_external_page_is_never_closed_even_on_errorpage(browser, tmp_path):
    from backend.app.services.sample_persistent_target import PersistentSampleTarget
    browser.targets.append({"id": "approved-external", "type": "page", "url":
        "https://affiliate.tiktokshopglobalselling.com/affiliate/sample/sample-request?shop_id=shop-7"})
    registry = PersistentSampleTarget(("shop-7", "free"), browser.browser, root=tmp_path)
    registry.save("approved-external", externally_owned=True)
    async with module.owned_sample_cdp("http://127.0.0.1:61000",
            persistent_key=("shop-7", "free"), registry_root=tmp_path):
        browser.targets[0]["url"] = "https://affiliate.tiktokshopglobalselling.com/errorpage"
    assert browser.created == browser.closed == []
    assert registry.is_externally_owned()
