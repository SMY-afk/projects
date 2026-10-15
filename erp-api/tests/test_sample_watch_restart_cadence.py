import json
from datetime import UTC, datetime, timedelta

from scripts import sample_capture_priority as module


def test_successful_watch_restart_waits_for_its_existing_next_cycle(tmp_path):
    now = datetime(2026, 10, 12, 5, 33, tzinfo=UTC)
    row = {
        "state": "idle",
        "last_success_at": (now - timedelta(seconds=30)).isoformat(),
        "next_due": (now + timedelta(seconds=180)).isoformat(),
    }
    (tmp_path / "cross-border-7.free-priority.json").write_text(json.dumps(row))
    assert (
        module.initial_free_delay("cross-border-7", 300, root=tmp_path, now=now) == 180
    )


def test_failed_watch_restart_can_recover_immediately(tmp_path):
    now = datetime(2026, 10, 12, 5, 33, tzinfo=UTC)
    (tmp_path / "cross-border-7.free-priority.json").write_text(
        json.dumps(
            {
                "state": "failed",
                "last_success_at": now.isoformat(),
                "next_due": (now + timedelta(seconds=300)).isoformat(),
            }
        )
    )
    assert module.initial_free_delay("cross-border-7", 300, root=tmp_path, now=now) == 0
