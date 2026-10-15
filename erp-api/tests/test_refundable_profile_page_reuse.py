import asyncio
import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from backend.app.services import refundable_creator_profile_capture as module


@pytest.fixture(autouse=True)
def fake_security_probe(monkeypatch):
    async def probe(page):
        return ("session_required", "captcha") if page.blocked else None
    monkeypatch.setattr(module, "page_security_failure", probe)


class ProfilePage:
    url = "https://affiliate.tiktokshopglobalselling.com/affiliate/sample/sample-request?shop_id=shop-7"

    def __init__(self, *, blocked=False):
        self.handler = None
        self.urls = []
        self.blocked = blocked

    def on(self, _event, handler):
        self.handler = handler

    def remove_listener(self, _event, handler):
        assert self.handler == handler
        self.handler = None

    async def goto(self, url, **_kwargs):
        self.urls.append(url)
        if self.blocked:
            raise RuntimeError("captcha")
        creator_id = parse_qs(urlsplit(url).query)["cid"][0]
        for kind, response_creator in [
            (1, "other-creator"),
            *[(n, creator_id) for n in range(1, 6)],
        ]:

            async def payload():
                return {"code": 0, "data": {}}

            self.handler(
                SimpleNamespace(
                    url="https://affiliate.tiktokshopglobalselling.com/oec/affiliate/creator/marketplace/profile",
                    status=200,
                    request=SimpleNamespace(
                        method="POST",
                        post_data=json.dumps(
                            {
                                "creator_oec_id": response_creator,
                                "profile_types": [kind],
                            }
                        ),
                    ),
                    json=payload,
                )
            )


@pytest.mark.asyncio
async def test_multiple_creators_reuse_the_paid_page(monkeypatch):
    def cannot_open_another_page():
        raise AssertionError("Profile collection opened another target")

    monkeypatch.setattr(module, "async_playwright", cannot_open_another_page)
    page = ProfilePage()
    rows = [
        {"creator": {"username": name, "creator_open_id": name}}
        for name in ("one", "two")
    ]
    result = await module.capture_refundable_profiles(
        "endpoint",
        "shop-7",
        rows,
        host="affiliate.tiktokshopglobalselling.com",
        reuse_page=page,
    )
    assert set(result) == {"one", "two"}
    assert [len(result[name]) for name in result] == [5, 5]
    assert len(page.urls) == 2


@pytest.mark.asyncio
async def test_reused_profile_captcha_propagates_to_shop_pause(monkeypatch):
    async def captcha(_page):
        return "session_required", "captcha"

    monkeypatch.setattr(module, "page_security_failure", captcha, raising=False)
    with pytest.raises(RuntimeError, match="captcha"):
        await module.capture_refundable_profiles(
            "endpoint",
            "shop-7",
            [{"creator": {"username": "one", "creator_open_id": "id"}}],
            host="affiliate.tiktokshopglobalselling.com",
            reuse_page=ProfilePage(blocked=True),
        )


@pytest.mark.asyncio
async def test_completed_profile_progress_is_reused_in_next_window():
    rows = {}
    cache = SimpleNamespace(
        load=lambda shop, creator, name: rows.get((shop, creator, name)),
        save=lambda shop, creator, name, result: rows.update(
            {(shop, creator, name): result}
        ),
    )
    page = ProfilePage()
    items = [
        {"creator": {"username": name, "creator_open_id": name}}
        for name in ("one", "two")
    ]
    for _ in range(2):
        result = await module.capture_refundable_profiles(
            "endpoint",
            "shop-7",
            items,
            host="affiliate.tiktokshopglobalselling.com",
            reuse_page=page,
            profile_cache=cache,
        )
        assert [len(result[name]) for name in result] == [5, 5]
    assert len(page.urls) == 2


@pytest.mark.asyncio
async def test_cancelled_window_keeps_each_already_completed_creator():
    saved = {}
    cache = SimpleNamespace(
        load=lambda shop, creator, name: saved.get((shop, creator, name)),
        save=lambda shop, creator, name, result: saved.update(
            {(shop, creator, name): result}
        ),
    )

    class CancelledPage(ProfilePage):
        async def goto(self, url, **kwargs):
            if len(self.urls) == 1:
                raise asyncio.CancelledError()
            await super().goto(url, **kwargs)

    items = [
        {"creator": {"username": name, "creator_open_id": name}}
        for name in ("one", "two")
    ]
    with pytest.raises(asyncio.CancelledError):
        await module.capture_refundable_profiles(
            "endpoint",
            "shop-7",
            items,
            host="affiliate.tiktokshopglobalselling.com",
            reuse_page=CancelledPage(),
            profile_cache=cache,
        )
    page = ProfilePage()
    result = await module.capture_refundable_profiles(
        "endpoint",
        "shop-7",
        items,
        host="affiliate.tiktokshopglobalselling.com",
        reuse_page=page,
        profile_cache=cache,
    )
    assert len(page.urls) == 1
    assert [len(result[name]) for name in result] == [5, 5]


@pytest.mark.asyncio
async def test_large_profile_scope_yields_without_losing_verified_progress():
    from tempfile import TemporaryDirectory
    from pathlib import Path
    from backend.app.services.refundable_profile_cache import RefundableProfileCache
    page = ProfilePage()
    items = [{"creator": {"username": str(n), "creator_open_id": str(n)},
              "product": {"sku_image_url": "https://example.test/image.png"}}
             for n in range(4)]
    with TemporaryDirectory() as directory:
        cache = RefundableProfileCache(root=Path(directory))
        result = await module.capture_refundable_profiles(
            "endpoint", "shop", items, host="affiliate.tiktokshopglobalselling.com",
            reuse_page=page, profile_cache=cache,
        )
        assert len(page.urls) == 3
        assert sorted(len(rows) for rows in result.values()) == [0, 5, 5, 5]
        result = await module.capture_refundable_profiles(
            "endpoint", "shop", items, host="affiliate.tiktokshopglobalselling.com",
            reuse_page=page, profile_cache=cache,
        )
        assert len(page.urls) == 4
        assert all(len(rows) == 5 for rows in result.values())


@pytest.mark.asyncio
async def test_reused_user_page_returns_to_samples_after_profile_capture():
    class NavigatingPage(ProfilePage):
        restored = False

        async def goto(self, url, **kwargs):
            if urlsplit(url).path == "/affiliate/sample/sample-request":
                self.restored = True
            else:
                await super().goto(url, **kwargs)
            self.url = url

    page = NavigatingPage()
    original = page.url
    await module.capture_refundable_profiles(
        "endpoint", "shop-7", [{"creator": {"username": "one", "creator_open_id": "one"}}],
        host="affiliate.tiktokshopglobalselling.com", reuse_page=page,
    )
    assert page.restored and page.url == original


@pytest.mark.asyncio
async def test_cross3_limits_expensive_profile_navigation_to_one_per_paid_window(tmp_path):
    from backend.app.services.refundable_profile_cache import RefundableProfileCache

    page = ProfilePage()
    items = [{"creator": {"username": str(n), "creator_open_id": str(n)},
              "product": {"sku_image_url": "https://example.test/image.png"}}
             for n in range(4)]
    result = await module.capture_refundable_profiles(
        "endpoint", "9622543325839925006", items,
        host="affiliate.tiktokshopglobalselling.com", reuse_page=page,
        profile_cache=RefundableProfileCache(root=tmp_path),
    )
    assert len(page.urls) == 1
    assert sorted(len(rows) for rows in result.values()) == [0, 0, 0, 5]
