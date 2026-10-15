"""Hidden SSH and durable metadata delivery; unknown outcomes query receipts first."""

import base64
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from backend.app.services.windows_background_process import background_process_options
from scripts.local_sample_metadata_rules import fresh

REMOTE_MODULES = (
    "local_sample_metadata_state", "local_sample_metadata_rules",
    "local_sample_metadata_db", "local_sample_metadata_remote",
)


def rpc(operation, payload):
    if operation not in {"probe", "status", "apply"}:
        raise ValueError("metadata_rpc_operation_invalid")
    sources = [(f"scripts.{name}", Path(__file__).with_name(f"{name}.py").read_text(encoding="utf-8"))
               for name in REMOTE_MODULES]
    envelope = {"sources": sources, "request": {**payload, "operation": operation}}
    encoded = base64.b64encode(json.dumps(envelope, ensure_ascii=False).encode()).decode()
    program = (
        "import base64,json,sys,types\n"
        f"bundle=json.loads(base64.b64decode({encoded!r}))\n"
        "for name, source in bundle['sources']:\n"
        " module=types.ModuleType(name); module.__package__='scripts'; module.__file__=name\n"
        " sys.modules[name]=module; exec(compile(source,name,'exec'),module.__dict__)\n"
        "sys.modules['scripts.local_sample_metadata_remote'].main(bundle['request'])\n"
    ).encode()
    try:
        result = subprocess.run([
            "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "erp-ecs",
            "docker exec -i erp-ecs-sample-worker-1 /opt/venv/bin/python -",
        ], input=program, capture_output=True, check=False, timeout=60,
            **background_process_options())
    except subprocess.TimeoutExpired as error:
        raise TimeoutError("metadata_ssh_timeout") from error
    if result.returncode or len(result.stdout) > 1_000_000:
        raise RuntimeError("metadata_ssh_failed")
    try:
        response = json.loads(result.stdout)
    except (ValueError, UnicodeDecodeError) as error:
        raise RuntimeError("metadata_rpc_reply_invalid") from error
    if not isinstance(response, dict) or not isinstance(response.get("status"), str):
        raise TypeError("metadata_rpc_reply_invalid")
    return response


def _require_receipt(row, receipt):
    if (receipt.get("status") != "completed" or receipt.get("result") != "metadataApplied"
            or receipt.get("attempt_id") != row["attempt_id"]
            or receipt.get("payload_hash") != row["payload_hash"]):
        raise RuntimeError("metadata_receipt_identity_invalid")


def deliver_pending(state, send=rpc):
    row = state.load_pending()
    if row is None:
        return {"status": "idle"}
    identity = {"attempt_id": row["attempt_id"], "payload_hash": row["payload_hash"]}
    if row["phase"] in {"submitting", "audit_required"}:
        result = send("status", identity)
        if result.get("status") == "completed":
            _require_receipt(row, result)
            state.mark_completed(row["attempt_id"], result)
            return result
        if result.get("status") != "not_found":
            return result
        if row["phase"] == "audit_required":
            return {"status": "audit_required", "reason": row["reason"]}
    observed = datetime.fromisoformat(row["capture"]["observed_at"])
    if not fresh(observed, datetime.now(UTC)):
        if row["phase"] == "captured":
            state.mark_superseded(row["attempt_id"], "capture_expired_before_submit")
            return {"status": "superseded", "reason": "capture_expired_before_submit"}
        state.mark_audit_required(row["attempt_id"], "unknown_remote_outcome_stale_capture")
        return {"status": "audit_required", "reason": "unknown_remote_outcome_stale_capture"}
    # Persist before the first network side effect. Crash/restart must never
    # confuse an unacknowledged submission with a brand-new captured batch.
    state.mark_submitting(row["attempt_id"])
    result = send("apply", {**identity, "manifest": row["manifest"], "capture": row["capture"]})
    if result.get("status") == "completed":
        _require_receipt(row, result)
        state.mark_completed(row["attempt_id"], result)
    elif (row["phase"] == "captured" and result.get("status") == "deferred"
          and result.get("no_metadata_write") is True):
        # This reply proves only the current submission did not write. It must
        # never erase uncertainty left by an earlier disconnected submission.
        state.mark_not_applied(row["attempt_id"], result)
        result = {**result, "known_unsubmitted": True}
    return result
