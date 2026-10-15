import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from scripts import sample_capture_priority as module


def test_partial_paid_retry_waits_for_a_new_free_success(tmp_path):
    now = datetime.now(UTC)
    args = SimpleNamespace(
        shop_label="cross-border-7", status_dir=tmp_path, guard_root=tmp_path, tabs=[3]
    )
    (tmp_path / "cross-border-7.attempts.json").write_text(
        json.dumps(
            {
                "3": (now - timedelta(minutes=20)).isoformat(),
            }
        )
    )
    (tmp_path / "cross-border-7.retry.json").write_text(
        json.dumps(
            {
                "state": "waiting_free",
                "tab": 3,
                "free_success_at": now.isoformat(),
            }
        )
    )
    free = tmp_path / "cross-border-7.free-priority.json"
    free.write_text(json.dumps({"last_success_at": now.isoformat()}))
    assert module.select_paid_tab(args) is None
    free.write_text(
        json.dumps({"last_success_at": (now + timedelta(minutes=5)).isoformat()})
    )
    assert module.select_paid_tab(args) == 3


def test_terminal_retry_cannot_starve_due_assignable_tabs(tmp_path):
    now = datetime.now(UTC)
    args = SimpleNamespace(status_dir=tmp_path, guard_root=tmp_path,
                           shop_label="cross-border-7", tabs=[1, 2, 3, 4, 5, 6])
    (tmp_path / "cross-border-7.retry.json").write_text(json.dumps({
        "state": "waiting_free", "tab": 5, "free_success_at": now.isoformat(),
    }))
    free = tmp_path / "cross-border-7.free-priority.json"
    free.write_text(json.dumps({"last_success_at": (now + timedelta(seconds=1)).isoformat()}))
    assert module.select_paid_tab(args) == 1


def test_terminal_retry_still_waits_when_active_tabs_are_not_due(tmp_path):
    now = datetime.now(UTC)
    args = SimpleNamespace(status_dir=tmp_path, guard_root=tmp_path,
                           shop_label="cross-border-12", tabs=[1, 2, 3, 4])
    (tmp_path / "cross-border-12.attempts.json").write_text(json.dumps({
        str(tab): now.isoformat() for tab in (1, 2, 3)
    }))
    (tmp_path / "cross-border-12.retry.json").write_text(json.dumps({
        "state": "waiting_free", "tab": 4, "free_success_at": now.isoformat(),
    }))
    (tmp_path / "cross-border-12.free-priority.json").write_text(json.dumps({
        "last_success_at": now.isoformat(),
    }))
    assert module.select_paid_tab(args) is None
