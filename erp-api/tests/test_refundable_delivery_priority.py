from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from scripts import run_refundable_sample_capture_loop as watcher


@pytest.mark.asyncio
async def test_http_delivery_does_not_hold_the_free_browser_capacity(monkeypatch, tmp_path):
    events = []

    @contextmanager
    def guard(label):
        try:
            yield
        finally:
            events.append("released")

    async def capture(args):
        events.append("captured")
        return True

    async def secondary(label, factory):
        return await factory()

    async def deliver(args):
        assert events[-1] == "released"
        events.append("delivered")

    monkeypatch.setattr(watcher, "browser_work", guard)
    monkeypatch.setattr(watcher, "cycle", capture)
    monkeypatch.setattr(watcher, "run_secondary", secondary)
    monkeypatch.setattr(watcher, "secondary_budget", lambda _label: 90)
    monkeypatch.setattr(watcher, "select_paid_tab", lambda _args: 1)
    monkeypatch.setattr(watcher, "deliver", deliver, raising=False)
    monkeypatch.setattr(watcher, "_write_status", lambda *a, **k: None)
    args = SimpleNamespace(shop_label="cross-border-3", status_dir=tmp_path,
                           interval_seconds=60, once=True, capture_only=False)
    await watcher.run(args)
    assert events == ["captured", "released", "delivered"]
