import subprocess
from datetime import UTC, datetime, timedelta

import pytest

from scripts.local_sample_metadata_state import MetadataCaptureState
from scripts.local_sample_metadata_transport import deliver_pending, rpc


def staged(tmp_path, *, age=0):
    state = MetadataCaptureState(tmp_path)
    row = state.stage({"rows": ["one"]}, {
        "observed_at": (datetime.now(UTC) - timedelta(seconds=age)).isoformat()})
    return state, row


def test_unknown_write_restart_checks_receipt_before_any_retry(tmp_path):
    state, row = staged(tmp_path)
    state.mark_submitting(row["attempt_id"])
    calls = []

    def send(operation, payload):
        calls.append(operation)
        return {"status": "completed", "attempt_id": row["attempt_id"],
                "payload_hash": row["payload_hash"], "result": "metadataApplied"}

    assert deliver_pending(state, send)["result"] == "metadataApplied"
    assert calls == ["status"]
    assert state.load_pending() is None


def test_network_error_retains_submitting_and_never_prints_payload(tmp_path):
    state, _ = staged(tmp_path)

    def send(_operation, _payload):
        raise TimeoutError("network uncertainty")

    with pytest.raises(TimeoutError):
        deliver_pending(state, send)
    assert state.load_pending()["phase"] == "submitting"


def test_stale_unknown_outcome_is_audit_not_automatic_replay(tmp_path):
    state, row = staged(tmp_path, age=901)
    state.mark_submitting(row["attempt_id"])
    calls = []

    def send(operation, _payload):
        calls.append(operation)
        return {"status": "not_found"}

    result = deliver_pending(state, send)
    assert calls == ["status"]
    assert result["status"] == "audit_required"
    assert state.load_pending()["phase"] == "audit_required"


def test_no_remote_receipt_mismatch_is_accepted(tmp_path):
    state, _ = staged(tmp_path)
    with pytest.raises(RuntimeError, match="receipt"):
        deliver_pending(state, lambda *_: {"status": "completed", "attempt_id": "wrong"})
    assert state.load_pending()["phase"] == "submitting"


def test_proven_no_write_deferral_can_recapture_later_without_fake_success(tmp_path):
    state, row = staged(tmp_path)
    reply = {"status": "deferred", "no_metadata_write": True,
             "reason": "sample_shop_busy", "attempt_id": row["attempt_id"],
             "payload_hash": row["payload_hash"]}
    assert deliver_pending(state, lambda *_: reply) == {**reply, "known_unsubmitted": True}
    assert state.load_pending()["phase"] == "captured"


def test_no_write_retry_does_not_erase_an_earlier_uncertain_submission(tmp_path):
    state, row = staged(tmp_path)
    state.mark_submitting(row["attempt_id"])

    def send(operation, _payload):
        if operation == "status":
            return {"status": "not_found"}
        return {"status": "deferred", "no_metadata_write": True,
                "attempt_id": row["attempt_id"], "payload_hash": row["payload_hash"]}

    result = deliver_pending(state, send)
    assert "known_unsubmitted" not in result
    assert state.load_pending()["phase"] == "submitting"


def test_known_unsubmitted_is_not_returned_before_durable_reset(tmp_path, monkeypatch):
    state, row = staged(tmp_path)
    reply = {"status": "deferred", "no_metadata_write": True, "reason": "sample_shop_busy",
             "attempt_id": row["attempt_id"], "payload_hash": row["payload_hash"]}

    def failed_reset(*_args):
        raise RuntimeError("metadata_state_write_verification_failed")

    monkeypatch.setattr(state, "mark_not_applied", failed_reset)
    with pytest.raises(RuntimeError, match="state_write"):
        deliver_pending(state, lambda *_: reply)
    assert state.load_pending()["phase"] == "submitting"


def test_ssh_is_hidden_fixed_command_and_payload_on_stdin(monkeypatch):
    calls = []

    def run(command, **options):
        calls.append((command, options))
        return subprocess.CompletedProcess(command, 0, stdout=b'{"status":"candidates"}', stderr=b'')

    monkeypatch.setattr("scripts.local_sample_metadata_transport.subprocess.run", run)
    assert rpc("probe", {})["status"] == "candidates"
    command, options = calls[0]
    assert command[-1] == "docker exec -i erp-ecs-sample-worker-1 /opt/venv/bin/python -"
    assert options["input"] and options["capture_output"]
    assert options["startupinfo"].wShowWindow == subprocess.SW_HIDE
    assert options.get("creationflags", 0) in {0, subprocess.CREATE_NO_WINDOW}
