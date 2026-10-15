"""A recovered local paid target requires live source identity before publishing."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.app.services import local_refundable_page_guard as guard

SHOP = "9136806951995371293"
URL = f"https://affiliate-us.tiktok.com/affiliate/sample/sample-request?shop_id={SHOP}&shop_region=US"


@pytest.fixture
def probes(monkeypatch):
    identities = AsyncMock(return_value=frozenset({SHOP}))
    security = AsyncMock(return_value=None)
    monkeypatch.setattr(guard, "read_cdp_platform_shop_ids", identities)
    monkeypatch.setattr(guard, "page_security_failure", security)
    return identities, security


@pytest.mark.asyncio
async def test_live_exact_local_page_is_required_after_navigation(probes):
    await guard.verify_local_paid_page(
        SimpleNamespace(url=URL), "http://localhost:58379", SHOP, "affiliate-us.tiktok.com"
    )
    probes[0].assert_awaited_once()
    probes[1].assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("url", [
    "https://affiliate-us.tiktok.com/affiliate/sample/sample-request",
    URL.replace(SHOP, "other"),
    URL.replace("affiliate-us.tiktok.com", "seller-us.tiktok.com"),
    URL.replace("sample-request", "creator/detail"),
])
async def test_wrong_page_identity_fails_closed(probes, url):
    with pytest.raises(RuntimeError, match="local_paid_page_identity_changed"):
        await guard.verify_local_paid_page(
            SimpleNamespace(url=url), "http://localhost:58379", SHOP, "affiliate-us.tiktok.com"
        )


@pytest.mark.asyncio
async def test_live_mixed_browser_identity_fails_closed(probes):
    probes[0].return_value = frozenset({SHOP, "other"})
    with pytest.raises(RuntimeError, match="local_paid_browser_identity_changed"):
        await guard.verify_local_paid_page(
            SimpleNamespace(url=URL), "http://localhost:58379", SHOP, "affiliate-us.tiktok.com"
        )


@pytest.mark.asyncio
async def test_captcha_after_navigation_blocks_raw_publication(probes):
    probes[1].return_value = ("captcha", "captcha")
    with pytest.raises(RuntimeError, match="captcha"):
        await guard.verify_local_paid_page(
            SimpleNamespace(url=URL), "http://localhost:58379", SHOP, "affiliate-us.tiktok.com"
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["host", "frame", "request_shop", "response_shop"])
async def test_real_response_evidence_cannot_cross_shop_or_host(probes, change):
    response = SimpleNamespace(
        url="https://affiliate-us.tiktok.com/api/v1/affiliate/sample/refundable/apply/list",
        request=SimpleNamespace(frame=SimpleNamespace(url=URL)),
    )
    request, payload = {}, {"data": {}}
    if change == "host":
        response.url = response.url.replace("affiliate-us.tiktok.com", "other.test")
    elif change == "frame":
        response.request.frame.url = URL.replace(SHOP, "other")
    elif change == "request_shop":
        request["shop_id"] = "other"
    else:
        payload["data"]["shop_id"] = "other"
    with pytest.raises(RuntimeError, match="local_paid_response_identity_changed"):
        await guard.verify_local_paid_response(
            SimpleNamespace(url=URL), response, request, payload,
            "http://localhost:58379", SHOP, "affiliate-us.tiktok.com"
        )


@pytest.mark.asyncio
async def test_other_shop_capture_is_not_changed(probes):
    await guard.verify_local_paid_page(SimpleNamespace(), "unused", "cross-shop", "other")
    probes[0].assert_not_awaited()
    probes[1].assert_not_awaited()


def test_owned_target_failure_is_not_misreported_as_generic_capture_or_captcha():
    from scripts.run_refundable_sample_capture_loop import failure_code

    assert failure_code(RuntimeError("owned_page_target_changed")) == "owned_page_target_changed"
    assert failure_code(RuntimeError("local_paid_page_identity_changed")) == "local_paid_page_identity_changed"


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["valid", "external", "different_target", "different_shop"])
async def test_landing_restore_requires_actual_registered_collector_target(probes, monkeypatch, tmp_path, case):
    from backend.app.services.sample_persistent_target import PersistentSampleTarget

    browser = "ws://browser/local"
    registry = PersistentSampleTarget((SHOP, "refundable"), browser, root=tmp_path)
    registry.save("owned-target", externally_owned=case == "external")
    landing = "https://seller-us.tiktok.com/affiliate/landing"
    if case == "different_shop":
        landing += "?shop_id=other"
    targets = [{"id": "owned-target", "type": "page", "url": landing}]

    class Client:
        async def get(self, url):
            result = {"webSocketDebuggerUrl": browser} if url.endswith("/json/version") else targets
            return SimpleNamespace(json=lambda: result)

    @asynccontextmanager
    async def client(**_kwargs):
        yield Client()

    monkeypatch.setattr(guard.httpx, "AsyncClient", client)
    monkeypatch.setattr(guard, "PersistentSampleTarget", lambda *_args: registry)
    session = SimpleNamespace(
        send=AsyncMock(return_value={"targetInfo": {"targetId": "other" if case == "different_target" else "owned-target", "url": landing}}),
        detach=AsyncMock(),
    )
    page = SimpleNamespace(url=landing, context=SimpleNamespace(new_cdp_session=AsyncMock(return_value=session)))

    async def goto(url, **_kwargs):
        page.url = url

    page.goto = AsyncMock(side_effect=goto)
    if case in {"external", "different_target"}:
        with pytest.raises(RuntimeError, match="owned_page_target_changed"):
            await guard.restore_local_owned_redirect(page, "endpoint", SHOP, "affiliate-us.tiktok.com", URL)
        page.goto.assert_not_awaited()
    else:
        restored = await guard.restore_local_owned_redirect(page, "endpoint", SHOP, "affiliate-us.tiktok.com", URL)
        assert restored == (case == "valid")
        assert page.goto.await_count == (case == "valid")
