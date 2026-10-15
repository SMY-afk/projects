from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from backend.app.services import refundable_page_controls as controls


@pytest.mark.asyncio
async def test_switch_to_cached_paid_panel_does_not_retry_an_already_selected_tab(monkeypatch):
    clicks = []

    class Tab:
        def filter(self, **kwargs): return self
        async def wait_for(self, **kwargs): pass
        async def count(self): return 1
        async def click(self, **kwargs): clicks.append(True)
        async def get_attribute(self, key): return "true"

    class Page:
        def get_by_role(self, role, **kwargs): return Tab()
        @asynccontextmanager
        async def expect_response(self, predicate, **kwargs):
            assert kwargs["timeout"] <= 5_000
            yield SimpleNamespace(value=None)
            raise PlaywrightTimeoutError("cached panel made no HTTP request")

    monkeypatch.setattr(controls, "page_security_failure", lambda _page: _false())
    assert await controls.select_paid_panel(Page(), lambda _r: True) is None
    assert len(clicks) == 1


async def _false():
    return None


@pytest.mark.asyncio
async def test_cached_selected_status_uses_one_alternate_active_tab_only():
    events = []
    selected = {"target": True}

    class Target:
        async def get_attribute(self, key): return "true" if selected["target"] else "false"

    class Alternative:
        def filter(self, **kwargs): return self
        async def count(self): return 1
        async def click(self, **kwargs):
            selected["target"] = False
            events.append("alternate-active")

    class Panel:
        def get_by_role(self, role, *, name):
            assert name.match("Shipped0"), "Ready-to-ship refresh must use another active paid tab"
            assert not name.match("All")
            assert not name.match("To review")
            return Alternative()

    await controls.reset_selected_status(Panel(), Target(), 1)
    assert events == ["alternate-active"]
