from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from erp_api.services.ziniao_webdriver_client import (
    ZiniaoCredentials,
    ZiniaoWebDriverClient,
    ZiniaoWebDriverError,
)


def _client(handler):
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport)
    return ZiniaoWebDriverClient("http://127.0.0.1:16888", http_client=http), http


def test_rejects_non_loopback_webdriver_url() -> None:
    with pytest.raises(ValueError, match="loopback"):
        ZiniaoWebDriverClient("https://example.com")


def test_lists_browsers_without_exposing_credentials() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "statusCode": "0",
                "err": "",
                "browserList": [
                    {
                        "browserOauth": "encrypted-shop-id",
                        "browserName": "TKUS24010801美区",
                        "siteId": "tiktok-shop-us",
                        "platform_id": "tiktok",
                        "platform_name": "TikTok Shop",
                    }
                ],
            },
        )

    async def run():
        client, http = _client(handler)
        try:
            credentials = ZiniaoCredentials("company", "user", "secret")
            browsers = await client.list_browsers(credentials)
            assert credentials.password not in repr(credentials)
            assert browsers[0].name == "TKUS24010801美区"
            assert browsers[0].oauth == "encrypted-shop-id"
            assert captured["action"] == "getBrowserList"
            assert captured["company"] == "company"
            assert captured["username"] == "user"
            assert captured["password"] == "secret"
            assert captured["requestId"]
        finally:
            await http.aclose()

    asyncio.run(run())


def test_starts_browser_and_parses_selenium_connection_details(tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["action"] == "startBrowser"
        assert payload["browserOauth"] == "encrypted-shop-id"
        assert payload["isHeadless"] is False
        assert payload["privacyMode"] is False
        assert payload["notPromptForDownload"] == 1
        return httpx.Response(
            200,
            json={
                "statusCode": 0,
                "err": "",
                "debuggingPort": "45678",
                "core_version": "192.0.2.1",
                "core_type": "Chromium",
                "downloadPath": str(tmp_path),
            },
        )

    async def run():
        client, http = _client(handler)
        try:
            session = await client.start_browser(
                ZiniaoCredentials("company", "user", "secret"),
                browser_oauth="encrypted-shop-id",
            )
            assert session.debugging_port == 45678
            assert session.core_major_version == 119
            assert session.debugger_address == "127.0.0.1:45678"
            assert session.download_path == tmp_path
        finally:
            await http.aclose()

    asyncio.run(run())


def test_stops_only_the_requested_browser() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={"statusCode": 0, "err": ""})

    async def run():
        client, http = _client(handler)
        try:
            await client.stop_browser(
                ZiniaoCredentials("company", "user", "secret"),
                browser_oauth="encrypted-shop-id",
            )
        finally:
            await http.aclose()

    asyncio.run(run())

    assert captured["action"] == "stopBrowser"
    assert captured["browserOauth"] == "encrypted-shop-id"
    assert captured["isHeadless"] is False


def test_infers_chromium_when_v6_omits_core_type(tmp_path) -> None:
    browser_path = tmp_path / "chrome_64_192.0.2.1"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "statusCode": 0,
                "err": "",
                "debuggingPort": 45678,
                "core_version": "192.0.2.1",
                "browserPath": str(browser_path),
            },
        )

    async def run():
        client, http = _client(handler)
        try:
            session = await client.start_browser(
                ZiniaoCredentials("company", "user", "secret"),
                browser_oauth="encrypted-shop-id",
            )
            assert session.core_type == "Chromium"
            assert session.browser_path == browser_path
        finally:
            await http.aclose()

    asyncio.run(run())


def test_uses_sanitized_ziniao_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"statusCode": -10003, "err": "登录失败（权限未开通）"},
        )

    async def run():
        client, http = _client(handler)
        try:
            with pytest.raises(ZiniaoWebDriverError) as caught:
                await client.list_browsers(
                    ZiniaoCredentials("company", "user", "secret")
                )
            assert caught.value.status_code == "-10003"
            assert "权限未开通" in str(caught.value)
            assert "secret" not in str(caught.value)
        finally:
            await http.aclose()

    asyncio.run(run())
