import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from scripts import paid_window_schedule as schedule
from scripts import run_refundable_sample_capture_loop as watcher
from scripts import sample_capture_priority as priority


@pytest.mark.asyncio
async def test_no_due_tab_never_acquires_browser_or_reports_free_wait(monkeypatch, tmp_path):
    states = []

    async def capacity(*args, **kwargs):
        pytest.fail("No due paid tab must not acquire browser capacity")

    monkeypatch.setattr(watcher, "select_paid_tab", lambda args: None)
    monkeypatch.setattr(watcher, "wait_for_browser_capacity", capacity)
    monkeypatch.setattr(watcher, "_write_status", lambda directory, label, state, *rest: states.append(state))
    args = SimpleNamespace(shop_label="cross-border-3", status_dir=tmp_path,
                           interval_seconds=60, once=True, capture_only=False)
    await watcher.run(args)
    assert states == ["idle"]


@pytest.mark.asyncio
async def test_cross3_free_window_handoff_does_not_sleep_another_minute(monkeypatch, tmp_path):
    events = []

    async def capacity(*args, **kwargs):
        events.append("capacity")
        if events.count("capacity") == 1:
            from scripts.local_capture_guard import CaptureGuardError
            raise CaptureGuardError("free_priority_wait")
        raise asyncio.CancelledError()

    async def wait(label, timeout):
        assert label == "cross-border-3" and 0 < timeout <= 65
        events.append("local_wait")
        return True

    async def sleep(seconds):
        pytest.fail("An available window must not be lost to another fixed sleep")

    monkeypatch.setattr(watcher, "select_paid_tab", lambda args: 1)
    monkeypatch.setattr(watcher, "wait_for_browser_capacity", capacity)
    monkeypatch.setattr(watcher, "wait_for_free_window", wait, raising=False)
    monkeypatch.setattr(watcher.asyncio, "sleep", sleep)
    monkeypatch.setattr(watcher, "_write_status", lambda *args: None)
    args = SimpleNamespace(shop_label="cross-border-3", status_dir=tmp_path,
                           interval_seconds=60, once=False, capture_only=False)
    with pytest.raises(asyncio.CancelledError):
        await watcher.run(args)
    assert events == ["capacity", "local_wait", "capacity"]


@pytest.mark.asyncio
async def test_wait_reads_only_local_budget_and_wakes_within_two_seconds(monkeypatch):
    clock = [0]
    budgets = iter([0, 0, 90])
    sleeps = []

    async def sleep(delay):
        sleeps.append(delay)
        clock[0] += delay

    monkeypatch.setattr(schedule, "monotonic", lambda: clock[0])
    monkeypatch.setattr(schedule, "secondary_budget", lambda label: next(budgets))
    monkeypatch.setattr(schedule.asyncio, "sleep", sleep)
    assert await schedule.wait_for_free_window("cross-border-3", 65)
    assert sleeps == [2, 2]


@pytest.mark.asyncio
async def test_wait_expires_without_inventing_a_success_or_extending_window(monkeypatch):
    clock = [0]

    async def sleep(delay):
        clock[0] += delay

    monkeypatch.setattr(schedule, "monotonic", lambda: clock[0])
    monkeypatch.setattr(schedule, "secondary_budget", lambda label: 0)
    monkeypatch.setattr(schedule.asyncio, "sleep", sleep)
    assert not await schedule.wait_for_free_window("cross-border-3", 5)
    assert clock[0] == 5


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["requested", "failed", "stale", "margin"])
async def test_local_wait_preserves_actual_priority_and_freshness(tmp_path, state):
    label = "cross-border-3"
    now = datetime.now(UTC)
    due = now + timedelta(seconds=40 if state == "margin" else 300)
    priority.finish_free(label, state != "failed", due, root=tmp_path)
    if state == "requested":
        priority.request_free(label, root=tmp_path)
    if state == "stale":
        path = tmp_path / f"{label}.free-priority.json"
        row = priority._read(path)
        row["last_success_at"] = (now - timedelta(seconds=901)).isoformat()
        priority._write(path, row)
    before = (tmp_path / f"{label}.free-priority.json").read_bytes()
    assert not await schedule.wait_for_free_window(label, 0, root=tmp_path)
    assert (tmp_path / f"{label}.free-priority.json").read_bytes() == before


@pytest.mark.asyncio
async def test_free_request_cancels_inflight_paid_work_and_wait_does_not_bypass_it(tmp_path):
    entered = asyncio.Event()
    released = []
    label = "cross-border-3"
    priority.finish_free(label, True, datetime.now(UTC) + timedelta(seconds=300), root=tmp_path)

    async def capture():
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            released.append(True)

    task = asyncio.create_task(priority.run_secondary(label, capture, root=tmp_path))
    await entered.wait()
    priority.request_free(label, root=tmp_path)
    with pytest.raises(priority.CaptureGuardError, match="free_priority_wait"):
        await task
    assert released == [True]
    assert not await schedule.wait_for_free_window(label, 0, root=tmp_path)


@pytest.mark.asyncio
async def test_local_window_wait_can_be_cancelled_without_changing_priority(monkeypatch):
    entered = asyncio.Event()

    async def sleep(delay):
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(schedule, "secondary_budget", lambda label: 0)
    monkeypatch.setattr(schedule.asyncio, "sleep", sleep)
    task = asyncio.create_task(schedule.wait_for_free_window("cross-border-3", 65))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_aggregate_status_is_capturing_when_the_paid_tab_starts(monkeypatch, tmp_path):
    states = []
    platform = watcher.SHOPS["cross-border-3"][2]

    async def endpoint(**kwargs):
        return "http://127.0.0.1:12345"

    async def ids(endpoint):
        return frozenset({platform})

    async def ready(*args):
        pass

    async def capture(*args, **kwargs):
        assert states == [("cross-border-3", "capturing"), ("cross-border-3-2", "capturing")]
        return SimpleNamespace(page_count=1, captured_total=5)

    monkeypatch.setattr(watcher, "select_paid_tab", lambda args: 2)
    monkeypatch.setattr(watcher, "discover_hubstudio_cdp_url", endpoint)
    monkeypatch.setattr(watcher, "assert_erp_hubstudio_cdp_url", lambda value: value)
    monkeypatch.setattr(watcher, "read_cdp_platform_shop_ids", ids)
    monkeypatch.setattr(watcher, "ensure_browser_ready", ready)
    monkeypatch.setattr(watcher, "mark_attempt", lambda *args: None)
    monkeypatch.setattr(watcher, "refundable_store", lambda *args: object())
    monkeypatch.setattr(watcher, "capture_refundable_status", capture)
    monkeypatch.setattr(watcher, "_write_status", lambda directory, label, state, *rest: states.append((label, state)))
    args = SimpleNamespace(shop_label="cross-border-3", spool_root=tmp_path, status_dir=tmp_path,
                           capture_only=True, capture_timeout=60)
    assert await watcher.cycle(args)


@pytest.mark.asyncio
async def test_aggregate_status_is_delivering_after_browser_capacity_is_released(monkeypatch, tmp_path):
    states = []

    async def send(args):
        assert states == [("cross-border-3", "delivering"), ("cross-border-3-2", "delivering")]

    monkeypatch.setattr(watcher, "send_batch", send)
    monkeypatch.setattr(watcher, "finish_paid_retry", lambda *args: None)
    monkeypatch.setattr(watcher, "_write_status", lambda directory, label, state, *rest: states.append((label, state)))
    args = SimpleNamespace(shop_label="cross-border-3", status_dir=tmp_path,
                           completed_paid_scope=(object(), 2))
    await watcher.deliver(args)
