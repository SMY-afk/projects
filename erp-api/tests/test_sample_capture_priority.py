import json
import subprocess
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from scripts import sample_capture_priority as priority


def test_paid_cannot_run_until_free_has_succeeded(tmp_path):
    assert priority.secondary_budget("cross-border-7", root=tmp_path) == 0
    priority.request_free("cross-border-7", root=tmp_path)
    assert priority.secondary_budget("cross-border-7", root=tmp_path) == 0


def test_paid_only_runs_with_margin_before_next_free_cycle(tmp_path):
    now = datetime.now(UTC)
    priority.finish_free(
        "cross-border-7", True, now + timedelta(seconds=300), root=tmp_path
    )
    assert priority.secondary_budget("cross-border-7", root=tmp_path) == 90
    priority.finish_free(
        "cross-border-7", True, now + timedelta(seconds=40), root=tmp_path
    )
    assert priority.secondary_budget("cross-border-7", root=tmp_path) == 0


def test_free_request_preempts_secondary_even_with_fresh_last_success(tmp_path):
    priority.finish_free(
        "cross-border-7",
        True,
        datetime.now(UTC) + timedelta(seconds=300),
        root=tmp_path,
    )
    priority.request_free("cross-border-7", root=tmp_path)
    assert priority.secondary_budget("cross-border-7", root=tmp_path) == 0


def test_free_failure_blocks_paid_instead_of_spending_more_browser_requests(tmp_path):
    priority.finish_free(
        "cross-border-7",
        False,
        datetime.now(UTC) + timedelta(seconds=300),
        root=tmp_path,
    )
    assert priority.secondary_budget("cross-border-7", root=tmp_path) == 0


def test_paid_selects_one_oldest_due_active_tab_before_terminal_tabs(tmp_path):
    args = SimpleNamespace(
        status_dir=tmp_path, shop_label="cross-border-7", tabs=[1, 2, 3, 4, 5, 6]
    )
    assert priority.select_paid_tab(args) == 1
    priority.mark_attempt(args, 1)
    assert priority.select_paid_tab(args) == 2
    priority.mark_attempt(args, 2)
    assert priority.select_paid_tab(args) == 3


def test_recent_paid_attempt_is_not_repeated_every_minute(tmp_path):
    args = SimpleNamespace(status_dir=tmp_path, shop_label="cross-border-7", tabs=[1])
    priority.mark_attempt(args, 1)
    assert priority.select_paid_tab(args) is None


@pytest.mark.parametrize("skew,allowed", [(0.5, True), (10, False), (-40, False)])
def test_remote_probe_allows_only_small_clock_skew(
    monkeypatch, tmp_path, skew, allowed
):
    row = {
        "shop": "local",
        "checked_at": (datetime.now(UTC) + timedelta(seconds=skew)).isoformat(),
        "state": "failed",
    }
    monkeypatch.setattr(
        priority.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout=json.dumps(row)),
    )
    if allowed:
        priority.refresh_official_free(root=tmp_path)
        assert priority.secondary_budget("local", root=tmp_path) == 0
    else:
        with pytest.raises(
            priority.CaptureGuardError, match="official_free_probe_invalid"
        ):
            priority.refresh_official_free(root=tmp_path)


def test_official_free_probe_timeout_is_not_a_browser_page_timeout(monkeypatch, tmp_path):
    def timeout(*args, **kwargs):
        assert kwargs["timeout"] == 30
        raise subprocess.TimeoutExpired("ssh", 30)

    monkeypatch.setattr(priority.subprocess, "run", timeout)
    with pytest.raises(priority.CaptureGuardError, match="official_free_probe_timeout"):
        priority.refresh_official_free(root=tmp_path)


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["free_priority_wait", "secondary_timeout"])
async def test_cleanup_timeout_does_not_replace_free_preemption_reason(monkeypatch, tmp_path, reason):
    import asyncio

    entered = asyncio.Event()
    priority.finish_free("cross-border-3", True, datetime.now(UTC) + timedelta(seconds=300), root=tmp_path)
    monkeypatch.setattr(priority, "secondary_budget", lambda *args, **kwargs: 1 if reason == "secondary_timeout" else 90)

    async def operation():
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            raise TimeoutError("Native page restoration did not acknowledge commit")

    task = asyncio.create_task(priority.run_secondary("cross-border-3", operation, root=tmp_path))
    await asyncio.wait_for(entered.wait(), timeout=3)
    if reason == "free_priority_wait":
        priority.request_free("cross-border-3", root=tmp_path)
    with pytest.raises(priority.CaptureGuardError, match=reason):
        await task


@pytest.mark.parametrize("remaining,budget", [(100, 70), (89, 0), (130, 90)])
def test_cross3_uses_a_bounded_short_window_without_moving_free_due(tmp_path, remaining, budget):
    priority.finish_free(
        "cross-border-3", True, datetime.now(UTC) + timedelta(seconds=remaining), root=tmp_path
    )
    path = tmp_path / "cross-border-3.free-priority.json"
    before = path.read_bytes()
    assert priority.secondary_budget("cross-border-3", root=tmp_path) == pytest.approx(budget, abs=0.1)
    assert path.read_bytes() == before
