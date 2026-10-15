import json
from pathlib import Path

import pytest

from scripts.local_sample_metadata_state import MetadataCaptureState


def test_pending_survives_restart_without_clearing_unknown_write(tmp_path):
    state = MetadataCaptureState(tmp_path)
    row = state.stage({"rows": ["one"]}, {"observed_at": "now"}, "raw/batch-1")
    state.mark_submitting(row["attempt_id"])
    reloaded = MetadataCaptureState(tmp_path).load_pending()
    assert reloaded["phase"] == "submitting"
    assert reloaded["raw_batch_dir"] == "raw/batch-1"
    assert state.stage(row["manifest"], row["capture"])["phase"] == "submitting"
    with pytest.raises(RuntimeError, match="must_not_be_overwritten"):
        state.stage({"rows": ["another"]}, {"observed_at": "later"})


def test_success_requires_exact_receipt_and_retains_history(tmp_path):
    state = MetadataCaptureState(tmp_path)
    row = state.stage({"rows": ["one"]}, {"observed_at": "now"})
    with pytest.raises(RuntimeError, match="receipt_identity"):
        state.mark_completed(row["attempt_id"], {"attempt_id": "other", "status": "completed"})
    state.mark_completed(row["attempt_id"], {"attempt_id": row["attempt_id"], "status": "completed"})
    assert state.load_pending() is None
    state.stage({"rows": ["two"]}, {"observed_at": "later"})
    assert (tmp_path / f'{row["attempt_id"]}.json').is_file()


def test_changed_capture_fails_closed(tmp_path):
    state = MetadataCaptureState(tmp_path)
    row = state.stage({"rows": ["one"]}, {"total": 2})
    path = tmp_path / f'{row["attempt_id"]}.json'
    data = json.loads(path.read_text())
    data["capture"]["total"] = 3
    path.write_text(json.dumps(data))
    with pytest.raises(RuntimeError, match="metadata_state_invalid"):
        state.load_pending()


def test_audit_state_never_resets_to_sendable(tmp_path):
    state = MetadataCaptureState(tmp_path)
    row = state.stage({}, {})
    state.mark_audit_required(row["attempt_id"], "unknown_remote_outcome")
    with pytest.raises(RuntimeError, match="requires_audit"):
        state.mark_submitting(row["attempt_id"])


def test_utf8_state_survives_a_non_utf8_windows_locale(tmp_path, monkeypatch):
    original = Path.read_text

    def windows_reader(path, encoding=None, **kwargs):
        return original(path, encoding=encoding or "cp936", **kwargs)

    monkeypatch.setattr(Path, "read_text", windows_reader)
    state = MetadataCaptureState(tmp_path)
    manifest, capture = {"creator": "达人"}, {"note": "样品申请"}
    row = state.stage(manifest, capture)
    assert MetadataCaptureState(tmp_path).load_pending()["manifest"] == manifest
    state.mark_completed(row["attempt_id"], {"status": "completed", "attempt_id": row["attempt_id"]})
    assert state.stage(manifest, capture)["capture"] == capture
