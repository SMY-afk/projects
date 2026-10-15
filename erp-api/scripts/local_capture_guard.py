"""Cross-process browser mutation guard; never owns or closes a browser."""

import asyncio
import json
import os
import re
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from backend.app.services.local_browser_security import browser_security_state

ROOT = Path(__file__).resolve().parents[1] / ".runtime/browser-capture-guards"
SECURITY_REASONS = {"captcha", "session_expired"}


class CaptureGuardError(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _path(label, root, suffix):
    if not re.fullmatch(r"local|cross-border-(3|4|7|12)", label):
        raise ValueError("Unknown capture shop")
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{label}.{suffix}"


def pause_reason(label, *, root=ROOT):
    path = _path(label, root, "pause.json")
    if not path.exists():
        return None
    try:
        reason = json.loads(path.read_text(encoding="utf-8"))["reason"]
        return reason if reason in SECURITY_REASONS else "guard_state_invalid"
    except (OSError, ValueError, KeyError, TypeError):
        return "guard_state_invalid"


def pause_shop(label, reason, *, root=ROOT):
    if reason not in SECURITY_REASONS:
        raise ValueError("Unknown security pause")
    target = _path(label, root, "pause.json")
    temporary = target.with_suffix(f".{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(
            {
                "shop": label,
                "reason": reason,
                "at": datetime.now(UTC).isoformat(),
            }
        ),
        encoding="utf-8",
    )
    os.replace(temporary, target)


@contextmanager
def _capture_capacity(root):
    """Two browser mutations across all shops; passive heartbeats are independent."""
    for slot in range(2):
        handle = (root / f"capture-capacity-{slot}.lock").open("a+b")
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            continue
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()
        return
    raise CaptureGuardError("capture_capacity_busy")


@contextmanager
def browser_work(label, *, root=ROOT, allow_paused=False):
    """Hold only the named shop; contention defers, it never spawns another task."""
    with _path(label, root, "lock").open("a+b") as handle:
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise CaptureGuardError("browser_busy") from error
        try:
            if not allow_paused and (reason := pause_reason(label, root=root)):
                raise CaptureGuardError(reason)
            with _capture_capacity(root):
                yield
        except Exception as error:
            reason = security_reason(error)
            if reason:
                pause_shop(label, reason, root=root)
            raise
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def security_reason(error):
    code = getattr(error, "code", "")
    if code in SECURITY_REASONS:
        return code
    message = str(error).casefold()
    if "captcha" in message:
        return "captcha"
    if "session_expired" in message or "session_required" in message:
        return "session_expired"
    return None


async def ensure_browser_ready(label, endpoint):
    state = await asyncio.wait_for(browser_security_state(endpoint), 15)
    if state in SECURITY_REASONS:
        pause_shop(label, state)
    if state != "online":
        raise CaptureGuardError(state)


async def confirm_recovery(label, endpoint, *, root=ROOT):
    """Call only after operator confirms login/CAPTCHA and shop identity is verified."""
    with browser_work(label, root=root, allow_paused=True):
        state = await asyncio.wait_for(browser_security_state(endpoint), 15)
        if state != "online":
            raise CaptureGuardError(state)
        path = _path(label, root, "pause.json")
        if path.exists():
            path.unlink()


def retry_delay(error, failures, normal):
    code = getattr(error, "code", "")
    if code in SECURITY_REASONS or code == "guard_state_invalid":
        return 300
    if code in {
        "browser_busy",
        "capture_capacity_busy",
        "busy",
        "queue_unavailable",
        "free_priority_wait",
        "official_free_probe_timeout",
        "official_free_probe_failed",
    }:
        return 60
    return min(900, max(300, normal) * 2 ** min(max(failures - 1, 0), 4))
