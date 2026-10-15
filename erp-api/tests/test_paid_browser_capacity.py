import asyncio
from contextlib import contextmanager

import pytest

from scripts import paid_browser_capacity as capacity
from scripts.local_capture_guard import CaptureGuardError


@pytest.mark.asyncio
async def test_waiting_paid_capture_does_not_drop_when_slot_is_temporarily_busy(monkeypatch):
    calls = []

    @contextmanager
    def guard(label):
        calls.append(label)
        if len(calls) == 1:
            raise CaptureGuardError("capture_capacity_busy")
        try:
            yield
        finally:
            calls.append("released")

    async def operation():
        calls.append("captured")
        return 7

    async def sleep(_delay):
        calls.append("waited")

    monkeypatch.setattr(capacity, "browser_work", guard)
    monkeypatch.setattr(capacity.asyncio, "sleep", sleep)
    assert await capacity.wait_for_browser_capacity("local", operation) == 7
    assert calls == ["local", "waited", "local", "captured", "released"]


@pytest.mark.asyncio
async def test_security_pause_is_never_retried_or_bypassed(monkeypatch):
    @contextmanager
    def guard(_label):
        raise CaptureGuardError("captcha")
        yield

    monkeypatch.setattr(capacity, "browser_work", guard)
    with pytest.raises(CaptureGuardError, match="captcha"):
        await capacity.wait_for_browser_capacity("cross-border-7", lambda: pytest.fail("captcha bypass"))


@pytest.mark.asyncio
async def test_expired_wait_does_not_start_browser_work(monkeypatch):
    @contextmanager
    def guard(_label):
        raise CaptureGuardError("capture_capacity_busy")
        yield

    times = iter([0, 46])
    monkeypatch.setattr(capacity, "monotonic", lambda: next(times))
    monkeypatch.setattr(capacity, "browser_work", guard)
    with pytest.raises(CaptureGuardError, match="capture_capacity_busy"):
        await capacity.wait_for_browser_capacity("local", lambda: pytest.fail("late mutation"))


@pytest.mark.asyncio
async def test_free_preemption_cancels_paid_capture_and_releases_its_slot(monkeypatch):
    entered = asyncio.Event()
    released = []

    @contextmanager
    def guard(_label):
        try:
            yield
        finally:
            released.append(True)

    async def operation():
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(capacity, "browser_work", guard)
    task = asyncio.create_task(capacity.wait_for_browser_capacity("local", operation))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert released == [True]


@pytest.mark.asyncio
async def test_free_request_preempts_capacity_wait_before_another_slot_attempt(monkeypatch):
    attempts = []

    @contextmanager
    def guard(_label):
        attempts.append(True)
        raise CaptureGuardError("capture_capacity_busy")
        yield

    async def sleep(_delay):
        pass

    budgets = iter([True, False])
    monkeypatch.setattr(capacity, "browser_work", guard)
    monkeypatch.setattr(capacity.asyncio, "sleep", sleep)
    with pytest.raises(CaptureGuardError, match="free_priority_wait"):
        await capacity.wait_for_browser_capacity("local", lambda: pytest.fail("priority bypass"),
                                                 can_wait=lambda: next(budgets))
    assert attempts == [True]
