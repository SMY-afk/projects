import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

from scripts import run_local_affiliate_heartbeat as heartbeat


def test_verified_cdp_url_is_reused_without_browser_discovery(monkeypatch) -> None:
    platform_shop_id = heartbeat.HUBSTUDIO_SHOPS["cross-border-4"][2]
    cdp_url = "http://127.0.0.1:9876"

    async def endpoint(_url):
        return True

    async def identity(_url):
        return frozenset({platform_shop_id})

    async def no_discovery(**_kwargs):
        raise AssertionError("Cached verified CDP must not scan other shops")

    @asynccontextmanager
    async def playwright():
        yield object()

    async def connect(_playwright, _url, **_kwargs):
        page = SimpleNamespace(
            url=f"https://affiliate-us.tiktok.com/data?shop_id={platform_shop_id}"
        )
        return SimpleNamespace(contexts=[SimpleNamespace(pages=[page])])

    async def state(_contexts):
        return "online"

    monkeypatch.setattr(heartbeat, "probe_cdp_endpoint", endpoint)
    monkeypatch.setattr(heartbeat, "read_cdp_platform_shop_ids", identity)
    monkeypatch.setattr(heartbeat, "discover_hubstudio_cdp_url", no_discovery)
    monkeypatch.setattr(heartbeat, "browser_security_state", state)
    assert asyncio.run(heartbeat.probe_shop("cross-border-4", cdp_url)) == (
        "online",
        cdp_url,
    )


def test_transient_cached_cdp_timeout_is_connecting_not_offline(monkeypatch) -> None:
    cdp_url = "http://127.0.0.1:9876"

    async def unavailable(_url):
        return False

    async def no_discovery(**_kwargs):
        raise AssertionError("Transient timeout must not scan other shops")

    async def no_sleep(_seconds):
        pass

    monkeypatch.setattr(heartbeat, "probe_cdp_endpoint", unavailable)
    monkeypatch.setattr(heartbeat, "discover_hubstudio_cdp_url", no_discovery)
    monkeypatch.setattr(heartbeat.asyncio, "sleep", no_sleep)
    assert asyncio.run(heartbeat.probe_shop("cross-border-4", cdp_url)) == (
        "connecting",
        cdp_url,
    )


def test_discovery_miss_rechecks_last_verified_shop_endpoint(monkeypatch) -> None:
    cdp_url = "http://127.0.0.1:9876"
    calls = []

    async def probe(label, cached):
        calls.append((label, cached))
        if cached is None:
            return "browser_offline", None
        return "online", cached

    monkeypatch.setattr(heartbeat, "probe_shop", probe)
    result = asyncio.run(
        heartbeat.probe_with_last_verified("cross-border-7", None, cdp_url)
    )
    assert result == ("online", cdp_url)
    assert calls == [
        ("cross-border-7", None),
        ("cross-border-7", cdp_url),
    ]


def test_last_verified_endpoint_does_not_mask_real_offline(monkeypatch) -> None:
    async def offline(_label, cached):
        return ("browser_offline", None) if cached is None else ("connecting", cached)

    monkeypatch.setattr(heartbeat, "probe_shop", offline)
    assert asyncio.run(
        heartbeat.probe_with_last_verified(
            "cross-border-7", None, "http://127.0.0.1:9876"
        )
    ) == ("browser_offline", None)
