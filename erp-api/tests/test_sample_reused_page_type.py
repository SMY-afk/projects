from types import SimpleNamespace

import pytest

from backend.app.services import sample_request_page_controls as module


@pytest.mark.asyncio
async def test_free_capture_switches_from_paid_before_review_and_date(monkeypatch):
    calls = []

    class Tab:
        selected = False

        def filter(self, **_kwargs):
            return self

        async def count(self):
            return 1

        async def wait_for(self, **_kwargs):
            pass

        async def get_attribute(self, _name):
            return "true" if self.selected else "false"

        async def click(self, **_kwargs):
            self.selected = True
            calls.append("free")

    async def review(_page):
        calls.append("review")

    async def sort(_page):
        calls.append("date")

    monkeypatch.setattr(module, "_select_review_status", review)
    monkeypatch.setattr(module, "_select_request_date", sort)
    page = SimpleNamespace(get_by_role=lambda *_args, **_kwargs: Tab())
    await module.prepare_sample_review_page(page, select_free=True)
    assert calls == ["free", "review", "date"]


@pytest.mark.asyncio
async def test_free_tab_waits_for_ui_after_page_reload():
    class Tab:
        loaded = False

        def filter(self, **_kwargs):
            return self

        async def wait_for(self, **_kwargs):
            self.loaded = True

        async def count(self):
            return 1 if self.loaded else 0

        async def get_attribute(self, _name):
            return "true"

    tab = Tab()
    await module.select_free_sample_tab(
        SimpleNamespace(get_by_role=lambda *_args, **_kwargs: tab)
    )
    assert tab.loaded
