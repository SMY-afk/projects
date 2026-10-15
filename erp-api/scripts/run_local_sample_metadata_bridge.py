"""Local-only durable metadata bridge; official worker retains all business gates."""

import argparse
import asyncio
import json
import os
import platform
from datetime import UTC, datetime
from pathlib import Path

from backend.app.services.windows_background_process import has_hidden_console
from scripts.local_capture_guard import CaptureGuardError, pause_reason, retry_delay
from scripts.local_sample_metadata_capture import capture, finish_raw
from scripts.local_sample_metadata_rules import (
    LOCAL_SHOP,
    LOCAL_TENANT,
    fresh,
    require_manifest,
)
from scripts.local_sample_metadata_state import MetadataCaptureState
from scripts.local_sample_metadata_transport import deliver_pending, rpc
from scripts.run_remote_sample_capture_loop import shop_process_lock
from scripts.sample_capture_priority import refresh_official_free

ROOT = Path(__file__).resolve().parents[1]
VERSION = "local-free-metadata-bridge-v2"


def require_probe(manifest):
    checked = datetime.fromisoformat(manifest["checked_at"])
    if (manifest.get("tenant_id") != LOCAL_TENANT or manifest.get("shop_id") != LOCAL_SHOP
            or not isinstance(manifest.get("rows"), list)
            or not fresh(checked, datetime.now(UTC), seconds=30)):
        raise RuntimeError("metadata_probe_scope_or_time_invalid")
    if manifest["rows"]:
        require_manifest(manifest)


async def cycle(root, *, send=rpc, take_capture=capture, refresh_priority=refresh_official_free):
    root = Path(root)
    state = MetadataCaptureState(root / "pending")
    if reason := pause_reason("local"):
        return {"status": "paused", "reason": reason}
    if pending := state.load_pending():
        result = await asyncio.to_thread(deliver_pending, state, send)
        if result.get("status") in {"completed", "superseded"} and pending.get("raw_batch_dir"):
            await asyncio.to_thread(finish_raw, root, pending,
                                    superseded=result["status"] == "superseded")
        return result
    finalized = state.load_finalized()
    if finalized and finalized.get("raw_batch_dir"):
        await asyncio.to_thread(finish_raw, root, finalized,
                                superseded=finalized["phase"] == "superseded")
    response = await asyncio.to_thread(send, "probe", {})
    if response.get("status") != "candidates":
        return {**response, "stage": "probe"}
    manifest = response["manifest"]
    require_probe(manifest)
    if not manifest["rows"]:
        return {"status": "idle", "candidate_count": 0}
    await asyncio.to_thread(refresh_priority)
    require_probe(manifest)
    # This is free work under the original per-shop lock, not a paid window.
    # The official success watermark is read-only and is never synthesized.
    captured, raw_path = await asyncio.wait_for(take_capture(manifest, root), timeout=240)
    pending = state.stage(manifest, captured, raw_path)
    if pending["phase"] in {"completed", "superseded"}:
        return {"status": "idle", "reason": "metadata_capture_already_finalized"}
    result = await asyncio.to_thread(deliver_pending, state, send)
    if result.get("status") in {"completed", "superseded"}:
        await asyncio.to_thread(finish_raw, root, pending,
                                superseded=result["status"] == "superseded")
    return {**result, "candidate_count": len(manifest["rows"])}


def safe_status(root, row):
    summary = {"version": VERSION, "shop": "local", "pid": os.getpid(),
               "checked_at": datetime.now(UTC).isoformat(),
               **{key: row[key] for key in (
                   "status", "reason", "result", "candidate_count", "matched_count",
                   "updated_count", "failure_count", "next_due", "stage", "known_unsubmitted",
               ) if key in row}}
    MetadataCaptureState(root)._write(root / "status.json", summary)
    print(json.dumps(summary), flush=True)


def result_delay(row, failures):
    if row["status"] in {"completed", "idle", "paused", "audit_required"}:
        return 300
    if (row["status"] == "blocked" and row.get("stage") == "probe"
            and row.get("reason") == "metadata_source_not_complete_success"):
        # A five-minute source job and five-minute probe can otherwise remain
        # phase-locked. Retry only the read-only probe; no UI/submit took place.
        return 60
    if (row["status"] == "deferred" and row.get("reason") == "sample_shop_busy"
            and row.get("known_unsubmitted") is True):
        # Only a confirmed, durably reset submission can reuse existing RAW
        # promptly. Unknown submissions keep receipt-first and normal backoff.
        return 60
    return min(900, 300 * 2 ** min(max(failures - 1, 0), 2))


async def run(args):
    failures = 0
    while True:
        try:
            row = await cycle(args.state_root)
            failures = 0 if row["status"] in {"completed", "idle"} else failures + 1
            delay = result_delay(row, failures)
        except Exception as error:  # noqa: BLE001 -- preserve state; no traceback/source secrets
            failures += 1
            reason = getattr(error, "code", None)
            if not reason:
                reason = str(error) if str(error).startswith("metadata_") else f"metadata_{type(error).__name__}"
            row = {"status": "failed", "reason": reason}
            delay = retry_delay(CaptureGuardError(reason), failures, 300)
        safe_status(args.state_root, {**row, "failure_count": failures,
                                     "next_due": datetime.fromtimestamp(datetime.now(UTC).timestamp() + delay, UTC).isoformat()})
        if args.once:
            return row
        remaining = delay
        while remaining > 0:
            await asyncio.sleep(min(60, remaining))
            remaining -= min(60, remaining)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-root", type=Path, default=ROOT / ".runtime/local-sample-metadata-bridge")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    args.state_root = args.state_root.resolve()
    if not args.state_root.is_relative_to(ROOT / ".runtime"):
        parser.error("State must remain in the project's private runtime directory")
    if os.name == "nt" and not has_hidden_console():
        parser.error("Use pythonw -m scripts.run_hidden_background -- -m scripts.run_local_sample_metadata_bridge")
    with shop_process_lock(args.state_root, "local-metadata"):
        asyncio.run(run(args))


if __name__ == "__main__":
    platform._wmi = None
    main()
