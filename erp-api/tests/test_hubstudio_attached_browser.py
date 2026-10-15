import asyncio
from pathlib import Path

import pytest

from backend.app.services.hubstudio_attached_browser import (
    connect_attached_hubstudio_browser,
)


def test_attached_browser_exposes_session_without_remote_close() -> None:
    events = []

    class RemoteBrowser:
        def __init__(self):
            self.contexts = ["context"]

        def on(self, event, callback):
            events.append((event, callback))

        async def close(self):
            raise AssertionError("remote HubStudio browser must stay open")

    class Chromium:
        async def connect_over_cdp(self, url):
            events.append(("connect", url))
            return RemoteBrowser()

    class Playwright:
        chromium = Chromium()

    attached = asyncio.run(
        connect_attached_hubstudio_browser(Playwright(), "http://127.0.0.1:51518")
    )
    callback = lambda: None
    attached.on("disconnected", callback)

    assert attached.contexts == ["context"]
    assert events == [
        ("connect", "http://127.0.0.1:51518"),
        ("disconnected", callback),
    ]
    with pytest.raises(AttributeError):
        attached.close()  # type: ignore[attr-defined]


def test_capture_session_uses_attached_browser_guard() -> None:
    source = (
        Path(__file__).parents[1]
        / "backend/app/services/tiktok_affiliate_capture_session.py"
    ).read_text(encoding="utf-8")

    assert "connect_attached_hubstudio_browser" in source
    assert ".connect_over_cdp(" not in source
