import json

from scripts.run_remote_sample_capture_loop import _write_status


def test_transport_failure_keeps_safe_trace_without_sensitive_message(tmp_path):
    try:
        raise RuntimeError('private-value-must-not-appear')
    except RuntimeError:
        _write_status(tmp_path, 'cross-border-12', 'failed', 'RuntimeError')
    data = json.loads((tmp_path / 'cross-border-12.status.json').read_text())
    assert data['failure_frames']
    assert all('/' not in frame and '\\' not in frame for frame in data['failure_frames'])
    assert 'private-value-must-not-appear' not in json.dumps(data)


def test_ambiguous_page_control_has_a_safe_category_without_its_message(tmp_path):
    try:
        raise RuntimeError("strict mode violation: private-selector-must-not-appear")
    except RuntimeError:
        _write_status(tmp_path, "cross-border-3", "failed", "RuntimeError")
    data = json.loads((tmp_path / "cross-border-3.status.json").read_text())
    assert data["error_code"] == "page_control_ambiguous"
    assert "private-selector-must-not-appear" not in json.dumps(data)
