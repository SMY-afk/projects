"""A stale sibling may not impersonate the paid target's real security state."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.app.services.sample_persistent_target import PersistentSampleTarget
from scripts import local_paid_readiness as readiness
from scripts.local_capture_guard import CaptureGuardError

SHOP = "9136806951995371293"
BROWSER = "ws://browser/local"
URL = f"https://affiliate-us.tiktok.com/affiliate/sample/sample-request?shop_id={SHOP}&shop_region=US"


@pytest.fixture
def source(monkeypatch, tmp_path):
    targets = [
        {"id": "paid", "type": "page", "url": URL},
        {"id": "sibling", "type": "page", "url": URL},
    ]
    registry = PersistentSampleTarget((SHOP, "refundable"), BROWSER, root=tmp_path)
    registry.save("paid")
    states = {"paid": "online", "sibling": TimeoutError()}
    pauses = []

    class Client:
        async def get(self, url):
            payload = {"webSocketDebuggerUrl": BROWSER} if url.endswith("/json/version") else targets
            return SimpleNamespace(json=lambda: payload, raise_for_status=lambda: None)

    @asynccontextmanager
    async def client(**_kwargs):
        yield Client()

    async def state(target):
        result = states[target["id"]]
        if isinstance(result, BaseException):
            raise result
        return result

    identities = AsyncMock(return_value=frozenset({SHOP}))
    monkeypatch.setattr(readiness.httpx, "AsyncClient", client)
    monkeypatch.setattr(readiness, "PersistentSampleTarget", lambda *_args: registry)
    monkeypatch.setattr(readiness, "read_cdp_platform_shop_ids", identities)
    monkeypatch.setattr(readiness, "_page_state", state)
    monkeypatch.setattr(readiness, "pause_shop", lambda *args: pauses.append(args))
    return SimpleNamespace(targets=targets, registry=registry, states=states, pauses=pauses, identities=identities)


@pytest.mark.asyncio
@pytest.mark.parametrize("sibling", [TimeoutError(), "connecting"])
async def test_real_owned_online_with_unrelated_stall_is_usable(source, sibling):
    source.states["sibling"] = sibling
    await readiness.ensure_local_paid_ready("http://localhost:58379")
    source.identities.assert_awaited_once()
    assert source.pauses == []


@pytest.mark.asyncio
@pytest.mark.parametrize("owned", [TimeoutError(), "connecting"])
async def test_owned_timeout_never_becomes_fake_online(source, owned):
    source.states["paid"] = owned
    with pytest.raises(CaptureGuardError, match="connecting"):
        await readiness.ensure_local_paid_ready("http://localhost:58379")


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["captcha", "session_expired"])
async def test_security_failure_on_any_real_business_page_still_pauses_shop(source, state):
    source.states["sibling"] = state
    with pytest.raises(CaptureGuardError, match=state):
        await readiness.ensure_local_paid_ready("http://localhost:58379")
    assert source.pauses == [("local", state)]


@pytest.mark.asyncio
async def test_external_registry_is_not_adopted_even_if_page_is_online(source):
    source.registry.save("paid", externally_owned=True)
    with pytest.raises(RuntimeError, match="owned_page_target_changed"):
        await readiness.ensure_local_paid_ready("http://localhost:58379")


@pytest.mark.asyncio
async def test_live_browser_shop_mismatch_still_fails_closed(source):
    source.identities.return_value = frozenset({SHOP, "other"})
    with pytest.raises(RuntimeError, match="local_paid_browser_identity_changed"):
        await readiness.ensure_local_paid_ready("http://localhost:58379")


@pytest.mark.asyncio
async def test_new_browser_digest_cannot_reuse_prior_registry(source):
    source.registry.browser = "0" * 64
    with pytest.raises(RuntimeError, match="owned_page_target_changed"):
        await readiness.ensure_local_paid_ready("http://localhost:58379")
