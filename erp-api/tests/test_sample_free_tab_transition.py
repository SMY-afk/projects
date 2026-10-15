from types import SimpleNamespace

import pytest
from playwright.async_api import Error as PlaywrightError

from backend.app.services.sample_request_page_controls import select_free_sample_tab


@pytest.mark.asyncio
async def test_transient_duplicate_tabs_settle_before_selection(monkeypatch):
    counts = iter([2, 2, 1])
    clicked = []

    async def count():
        return next(counts, 1)

    async def wait_for(**_kwargs):
        return None

    async def selected(_name):
        return "true"

    async def click(**_kwargs):
        clicked.append(True)

    async def sleep(_delay):
        return None

    tab = SimpleNamespace(filter=lambda **_kwargs: tab, count=count,
                          wait_for=wait_for, get_attribute=selected, click=click)
    monkeypatch.setattr("backend.app.services.sample_request_page_controls.asyncio.sleep", sleep)
    await select_free_sample_tab(SimpleNamespace(get_by_role=lambda *a, **k: tab))
    assert clicked == []


@pytest.mark.asyncio
async def test_persistent_duplicate_tabs_remain_blocked(monkeypatch):
    async def count():
        return 2

    async def wait_for(**_kwargs):
        return None

    async def sleep(_delay):
        return None

    tab = SimpleNamespace(filter=lambda **_kwargs: tab, count=count, wait_for=wait_for)
    monkeypatch.setattr("backend.app.services.sample_request_page_controls.asyncio.sleep", sleep)
    with pytest.raises(RuntimeError, match="sample_free_tab_unavailable"):
        await select_free_sample_tab(SimpleNamespace(get_by_role=lambda *a, **k: tab))


@pytest.mark.asyncio
async def test_wait_for_free_tab_selection_before_checking_the_state():
    class Tab:
        clicked = False
        probes = 0

        def filter(self, **kwargs):
            return self

        async def wait_for(self, **kwargs):
            pass

        async def count(self):
            return 1

        async def click(self, **kwargs):
            self.clicked = True

        async def get_attribute(self, key):
            if self.clicked:
                self.probes += 1
            return "true" if self.probes >= 2 else "false"

    tab = Tab()
    await select_free_sample_tab(SimpleNamespace(get_by_role=lambda *a, **k: tab))
    assert tab.probes >= 2


@pytest.mark.asyncio
async def test_free_tab_waits_for_react_remount_after_visibility_probe():
    class Tab:
        probes = 0

        def filter(self, **kwargs):
            return self

        async def wait_for(self, **kwargs):
            pass

        async def count(self):
            self.probes += 1
            return 0 if self.probes == 1 else 1

        async def get_attribute(self, key):
            return "true"

    tab = Tab()
    await select_free_sample_tab(SimpleNamespace(get_by_role=lambda *a, **k: tab))
    assert tab.probes >= 2


@pytest.mark.asyncio
async def test_strict_visibility_probe_waits_for_unique_free_tab(monkeypatch):
    class Tab:
        probes = 0
        clicked = False

        def filter(self, **_kwargs):
            return self

        async def count(self):
            self.probes += 1
            return 2 if self.probes < 3 else 1

        async def wait_for(self, **_kwargs):
            if self.probes < 3:
                raise PlaywrightError("strict mode violation: locator resolved to 2 elements")

        async def get_attribute(self, _name):
            return "true"

        async def click(self, **_kwargs):
            self.clicked = True

    async def sleep(_delay):
        return None

    tab = Tab()
    monkeypatch.setattr("backend.app.services.sample_request_page_controls.asyncio.sleep", sleep)
    await select_free_sample_tab(SimpleNamespace(get_by_role=lambda *a, **k: tab))
    assert tab.probes >= 3
    assert not tab.clicked


@pytest.mark.asyncio
async def test_remounted_free_selection_never_clicks_duplicate_tabs(monkeypatch):
    class Tab:
        probes = 0
        clicked = 0

        def filter(self, **_kwargs):
            return self

        async def wait_for(self, **_kwargs):
            pass

        async def count(self):
            return 1

        async def get_attribute(self, _name):
            self.probes += 1
            if self.probes == 1:
                raise PlaywrightError("strict mode violation: locator resolved to 2 elements")
            return "true"

        async def click(self, **_kwargs):
            self.clicked += 1

    async def sleep(_delay):
        return None

    tab = Tab()
    monkeypatch.setattr("backend.app.services.sample_request_page_controls.asyncio.sleep", sleep)
    await select_free_sample_tab(SimpleNamespace(get_by_role=lambda *a, **k: tab))
    assert tab.probes >= 2
    assert tab.clicked == 0
