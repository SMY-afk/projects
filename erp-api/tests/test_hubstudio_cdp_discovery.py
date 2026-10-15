import asyncio

from backend.app.services.hubstudio_cdp import (
    _read_seller_storage_shop_ids,
    discover_hubstudio_cdp_url,
    parse_hubstudio_cdp_ports,
    read_cdp_platform_shop_ids,
)


def test_parses_unique_remote_debugging_ports_without_retaining_command_lines() -> None:
    commands = [
        "hubstudio.exe --remote-debugging-port=54242 --sub-token=secret",
        "hubstudio.exe --remote-debugging-port 55111 --other=value",
        "hubstudio.exe --remote-debugging-port=54242 --type=renderer",
        "chrome.exe --remote-debugging-port=9222",
    ]

    assert parse_hubstudio_cdp_ports(commands) == [54242, 55111]


def test_discovery_prefers_current_endpoint_then_changed_hubstudio_port() -> None:
    probes: list[str] = []

    async def probe(url: str) -> bool:
        probes.append(url)
        return url.endswith(":55111")

    resolved = asyncio.run(
        discover_hubstudio_cdp_url(
            current_url="http://127.0.0.1:54242",
            command_line_reader=lambda: [
                "hubstudio.exe --remote-debugging-port=55111 --sub-token=secret"
            ],
            probe=probe,
        )
    )

    assert resolved == "http://127.0.0.1:55111"
    assert probes == ["http://127.0.0.1:54242", "http://127.0.0.1:55111"]


def test_discovery_returns_none_when_hubstudio_is_offline() -> None:
    async def probe(_url: str) -> bool:
        return False

    assert (
        asyncio.run(
            discover_hubstudio_cdp_url(
                current_url=None,
                command_line_reader=list,
                probe=probe,
            )
        )
        is None
    )


def test_discovery_selects_the_endpoint_for_the_configured_shop() -> None:
    async def probe(_url: str) -> bool:
        return True

    async def shop_probe(url: str, shop_id: str) -> bool:
        return url.endswith(":64258") and shop_id == "9768147009521852682"

    resolved = asyncio.run(
        discover_hubstudio_cdp_url(
            current_url="http://127.0.0.1:51151",
            command_line_reader=lambda: [
                "hubstudio.exe --remote-debugging-port=60495",
                "hubstudio.exe --remote-debugging-port=64258",
            ],
            probe=probe,
            expected_platform_shop_id="9768147009521852682",
            shop_probe=shop_probe,
        )
    )

    assert resolved == "http://127.0.0.1:64258"


def test_explicit_current_endpoint_can_bootstrap_shop_validation() -> None:
    shop_probe_calls = []

    async def probe(url: str) -> bool:
        return url.endswith(":56722")

    async def shop_probe(url: str, shop_id: str) -> bool:
        shop_probe_calls.append((url, shop_id))
        return False

    resolved = asyncio.run(
        discover_hubstudio_cdp_url(
            current_url="http://127.0.0.1:56722",
            command_line_reader=list,
            probe=probe,
            expected_platform_shop_id="9768147009521852682",
            shop_probe=shop_probe,
            trust_current_url=True,
        )
    )

    assert resolved == "http://127.0.0.1:56722"
    assert shop_probe_calls == []


def test_page_shop_reader_accepts_only_page_target_shop_identifiers(
    monkeypatch,
) -> None:
    class Response:
        status_code = 200

        def json(self):
            return [
                {"type": "page", "url": "https://seller.test/?shop_id=shop-1"},
                {
                    "type": "page",
                    "url": "https://seller.test/?oec_seller_id=shop-2",
                },
                {"type": "worker", "url": "https://seller.test/?shop_id=ignored"},
            ]

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, _url):
            return Response()

    monkeypatch.setattr(
        "backend.app.services.hubstudio_cdp.httpx.AsyncClient",
        lambda **_kwargs: Client(),
    )

    assert asyncio.run(read_cdp_platform_shop_ids("http://127.0.0.1:51111")) == (
        frozenset({"shop-1", "shop-2"})
    )


def test_page_shop_reader_uses_seller_storage_when_urls_have_no_shop_id(
    monkeypatch,
) -> None:
    class Response:
        status_code = 200

        def json(self):
            return [{"type": "page", "url": "https://seller.tiktokshopglobalselling.com/affiliate/landing"}]

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, _url):
            return Response()

    async def storage_reader(_url):
        return frozenset({"9472478445887813622"})

    monkeypatch.setattr(
        "backend.app.services.hubstudio_cdp.httpx.AsyncClient",
        lambda **_kwargs: Client(),
    )
    monkeypatch.setattr(
        "backend.app.services.hubstudio_cdp._read_seller_storage_shop_ids",
        storage_reader,
        raising=False,
    )

    assert asyncio.run(read_cdp_platform_shop_ids("http://127.0.0.1:51111")) == (
        frozenset({"9472478445887813622"})
    )


def test_seller_storage_reader_does_not_close_externally_owned_browser(monkeypatch) -> None:
    class Page:
        url = "https://seller.tiktokshopglobalselling.com/affiliate/landing"

        async def evaluate(self, _expression):
            return "shop_id=9472478445887813622"

    class Browser:
        def __init__(self):
            self.contexts = [type("Context", (), {"pages": [Page()]})()]

        async def close(self):
            raise AssertionError("Externally owned HubStudio browser must stay open")

    class Chromium:
        async def connect_over_cdp(self, _url, *, timeout):
            assert timeout == 5000
            return Browser()

    class Playwright:
        chromium = Chromium()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    monkeypatch.setattr("playwright.async_api.async_playwright", lambda: Playwright())

    assert asyncio.run(_read_seller_storage_shop_ids("http://127.0.0.1:51111")) == (
        frozenset({"9472478445887813622"})
    )
