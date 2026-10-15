"""An unresponsive browser candidate must not stop other shop discovery."""

import asyncio

import pytest

from backend.app.services import hubstudio_cdp as cdp


@pytest.mark.asyncio
async def test_hung_shop_probe_moves_to_next_browser(monkeypatch):
    async def endpoint(_):
        return True

    async def shop(url, _):
        if url.endswith(":50001"):
            await asyncio.Future()
        return url.endswith(":50002")

    monkeypatch.setattr(cdp, "CDP_SHOP_PROBE_TIMEOUT_SECONDS", 0.02, raising=False)
    result = await asyncio.wait_for(cdp.discover_hubstudio_cdp_url(
        current_url=None, expected_platform_shop_id="shop",
        command_line_reader=lambda: [
            "hubstudio.exe --remote-debugging-port=50001",
            "hubstudio.exe --remote-debugging-port=50002",
        ], probe=endpoint, shop_probe=shop,
    ), 0.2)
    assert result == "http://127.0.0.1:50002"
