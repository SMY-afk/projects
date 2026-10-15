import asyncio
from argparse import Namespace

import pytest

from backend.app.services import sample_raw_capture_retry as retry
from scripts import run_auto_affiliate_exports as exports


@pytest.mark.asyncio
async def test_retry_waits_and_rechecks_security_before_replaying(monkeypatch):
    calls = []

    async def capture(*_args, **_kwargs):
        calls.append("capture")
        raise RuntimeError("terminal page missing")

    async def sleep(seconds):
        calls.append(seconds)

    async def probe(_endpoint):
        calls.append("probe")
        return "captcha"

    class Store:
        def abandon_capturing(self, _reason):
            return 1

    monkeypatch.setattr(retry, "capture_review_batch", capture)
    monkeypatch.setattr(retry.asyncio, "sleep", sleep)
    monkeypatch.setattr(retry, "browser_security_state", probe)
    with pytest.raises(RuntimeError, match="captcha"):
        await retry.capture_review_batch_with_retry(
            "endpoint", "shop", Store(), timeout_seconds=30
        )
    assert calls == ["capture", 30, "probe"]


@pytest.mark.asyncio
async def test_export_preemption_waits_for_nested_capture_cleanup(
    monkeypatch, tmp_path
):
    started, stopped = asyncio.Event(), asyncio.Event()

    async def capture(_args):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    monkeypatch.setattr(exports, "send_export", capture)
    monkeypatch.setattr(
        exports, "export_args", lambda *_: Namespace(spool_dir=tmp_path)
    )
    monkeypatch.setattr(
        exports, "sample_idle_status", lambda *_args, **_kwargs: "stored"
    )
    task = asyncio.create_task(
        exports.execute_window(
            Namespace(sample_status_dir=tmp_path, capture_timeout=60),
            {},
            {},
            "cross-border-4",
        )
    )
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    try:
        assert stopped.is_set(), "Nested browser task escaped priority cancellation"
    finally:
        for child in asyncio.all_tasks():
            if (
                child is not asyncio.current_task()
                and child.get_coro().__name__ == "capture"
            ):
                child.cancel()
                await asyncio.gather(child, return_exceptions=True)
