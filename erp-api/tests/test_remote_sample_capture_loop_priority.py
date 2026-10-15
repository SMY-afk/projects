import asyncio
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

from scripts import run_remote_sample_capture_loop as watcher


def test_each_sample_cycle_announces_capture_before_running(
    monkeypatch, tmp_path: Path
) -> None:
    states = []

    async def fake_cycle(_args):
        states.append("cycle")

    monkeypatch.setattr(watcher, "cycle", fake_cycle)
    monkeypatch.setattr(watcher, "browser_work", lambda _label: nullcontext())
    monkeypatch.setattr(watcher, "request_free", lambda _label: None)
    monkeypatch.setattr(watcher, "finish_free", lambda *_args: None)
    monkeypatch.setattr(
        watcher,
        "_write_status",
        lambda _dir, _shop, state, *_rest: states.append(state),
    )
    args = SimpleNamespace(
        status_dir=tmp_path,
        shop_label="cross-border-3",
        once=True,
        interval_seconds=300,
    )
    asyncio.run(watcher.run(args))
    assert states == ["starting", "capturing", "cycle", "stored"]
