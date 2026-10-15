"""Persist free-sample priority and bound each lower-priority browser operation."""

import asyncio
import json
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

from backend.app.services.windows_background_process import background_process_options
from scripts.local_capture_guard import ROOT, CaptureGuardError, _path

MAX_SECONDARY_SECONDS = 90
MIN_CROSS3_SECONDARY_SECONDS = 60
FREE_MARGIN_SECONDS = 30


def _read(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write(path, row):
    temporary = path.with_suffix(f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(row), encoding="utf-8")
    os.replace(temporary, path)


def request_free(label, *, root=ROOT):
    path = _path(label, root, "free-priority.json")
    row = _read(path)
    row.update(state="requested", at=datetime.now(UTC).isoformat())
    _write(path, row)


def finish_free(label, success, next_due, *, root=ROOT):
    path = _path(label, root, "free-priority.json")
    row = _read(path)
    row.update(state="idle" if success else "failed", next_due=next_due.isoformat())
    if success:
        row["last_success_at"] = datetime.now(UTC).isoformat()
    _write(path, row)


def initial_free_delay(label, interval, *, root=ROOT, now=None):
    row = _read(_path(label, root, "free-priority.json"))
    now = now or datetime.now(UTC)
    try:
        age = (now - datetime.fromisoformat(row["last_success_at"])).total_seconds()
        delay = (datetime.fromisoformat(row["next_due"]) - now).total_seconds()
    except (KeyError, ValueError, TypeError):
        return 0
    if row.get("state") != "idle" or not 0 <= age <= 900:
        return 0
    return min(interval, max(0, delay))


def secondary_budget(label, *, root=ROOT):
    row = _read(_path(label, root, "free-priority.json"))
    try:
        now = datetime.now(UTC)
        age = (now - datetime.fromisoformat(row["last_success_at"])).total_seconds()
        remaining = (datetime.fromisoformat(row["next_due"]) - now).total_seconds()
    except (KeyError, ValueError, TypeError):
        return 0
    if row.get("state") != "idle" or not 0 <= age <= 900:
        return 0
    minimum = MIN_CROSS3_SECONDARY_SECONDS if label == "cross-border-3" else MAX_SECONDARY_SECONDS
    if label == "local" and row.get("source_policy_result") == "official_api_available":
        minimum = MIN_CROSS3_SECONDARY_SECONDS
    if remaining < minimum + FREE_MARGIN_SECONDS:
        return 0
    return min(MAX_SECONDARY_SECONDS, remaining - FREE_MARGIN_SECONDS)


def refresh_official_free(*, root=ROOT):
    try:
        return _refresh_official_free(root=root)
    except subprocess.TimeoutExpired as error:
        raise CaptureGuardError("official_free_probe_timeout") from error


def _refresh_official_free(*, root):
    script = Path(__file__).with_name("probe_local_free_priority.py")
    result = subprocess.run(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=8",
            "erp-ecs",
            "docker exec -i erp-ecs-sample-worker-1 python -",
        ],
        input=script.read_bytes(),
        capture_output=True,
        check=False,
        timeout=30,
        **background_process_options(),
    )
    if result.returncode:
        raise CaptureGuardError("official_free_probe_failed")
    row = json.loads(result.stdout)
    checked = datetime.fromisoformat(row["checked_at"])
    if row["shop"] != "local" or not timedelta(seconds=-5) <= datetime.now(
        UTC
    ) - checked < timedelta(seconds=30):
        raise CaptureGuardError("official_free_probe_invalid")
    _write(_path("local", root, "free-priority.json"), row)


async def run_secondary(label, operation, *, root=ROOT):
    """A factory prevents starting browser work before priority checks pass."""
    budget = secondary_budget(label, root=root)
    if not budget:
        raise CaptureGuardError("free_priority_wait")
    task = asyncio.create_task(operation())
    deadline = asyncio.get_running_loop().time() + budget
    primary_error = None
    try:
        while not task.done():
            row = _read(_path(label, root, "free-priority.json"))
            if row.get("state") != "idle":
                raise CaptureGuardError("free_priority_wait")
            if asyncio.get_running_loop().time() >= deadline:
                raise CaptureGuardError("secondary_timeout")
            await asyncio.sleep(1)
        return await task
    except BaseException as error:
        primary_error = error
        raise
    finally:
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception as error:
                if primary_error is None:
                    raise
                print(
                    f"SECONDARY_CLEANUP_FAILED shop={label} "
                    f"error={type(error).__name__} preserving={type(primary_error).__name__}",
                    flush=True,
                )


def mark_attempt(args, tab):
    args.status_dir.mkdir(parents=True, exist_ok=True)
    path = args.status_dir / f"{args.shop_label}.attempts.json"
    row = _read(path)
    row[str(tab)] = datetime.now(UTC).isoformat()
    _write(path, row)
    args.active_paid_tab = tab
    args.active_free_success = _read(
        _path(args.shop_label, getattr(args, "guard_root", ROOT), "free-priority.json")
    ).get("last_success_at")


def mark_paid_retry(args):
    _write(
        args.status_dir / f"{args.shop_label}.retry.json",
        {
            "state": "waiting_free",
            "tab": args.active_paid_tab,
            "free_success_at": args.active_free_success,
        },
    )


def finish_paid_retry(args, tab):
    path = args.status_dir / f"{args.shop_label}.retry.json"
    row = _read(path)
    if row.get("state") == "waiting_free" and row.get("tab") == tab:
        row["state"] = "complete"
        _write(path, row)


def select_paid_tab(args):
    due = _due_paid_tabs(args)
    retry = _read(args.status_dir / f"{args.shop_label}.retry.json")
    if retry.get("state") == "waiting_free":
        # A failed non-assignable terminal tab must not pin every future round.
        active = [entry for entry in due if entry[2] in (1, 2, 3)]
        if retry.get("tab") not in (1, 2, 3) and active:
            return min(active)[2]
        free = _read(
            _path(
                args.shop_label,
                getattr(args, "guard_root", ROOT),
                "free-priority.json",
            )
        )
        if not free.get("last_success_at") or free["last_success_at"] == retry.get(
            "free_success_at"
        ):
            return None
        if retry.get("tab") in args.tabs:
            return retry["tab"]
    return min(due)[2] if due else None


def _due_paid_tabs(args):
    now = datetime.now(UTC)
    attempts = _read(args.status_dir / f"{args.shop_label}.attempts.json")
    due = []
    for tab in args.tabs:
        try:
            attempted = datetime.fromisoformat(attempts[str(tab)])
        except (KeyError, ValueError, TypeError):
            attempted = datetime.min.replace(tzinfo=UTC)
        interval = timedelta(minutes=10 if tab in (1, 2, 3) else 30)
        if now - attempted >= interval:
            due.append((tab not in (1, 2, 3), attempted, tab))
    return due
