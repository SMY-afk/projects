import asyncio
from datetime import date

from backend.app.services import tiktok_affiliate_available_date as availability


def test_creator_probe_waits_for_hydrated_date_picker(monkeypatch) -> None:
    calls = []

    class Locator:
        async def wait_for(self, **_):
            calls.append("wait")

        async def click(self):
            assert "wait" in calls
            calls.append("click")

        def locator(self, selector):
            return Panels() if selector == ".arco-panel-date-inner" else self

        async def inner_text(self):
            return "2026/10"

        async def all_text_contents(self):
            return ["4"]

    class Panels:
        async def count(self):
            return 1

        def nth(self, _):
            return Locator()

    class Page:
        keyboard = type("Keyboard", (), {"press": lambda *_: asyncio.sleep(0)})()

        def locator(self, _):
            return Locator()

    async def secure(_):
        return None

    monkeypatch.setattr(availability, "page_security_failure", secure)

    result = asyncio.run(availability._detect_page_date(Page(), "creators", refresh=False))

    assert result == date(2026, 10, 4)
    assert calls[:2] == ["wait", "click"]
