"""Local export status and process ownership persistence."""

import json
import os
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path


def write_status(path: Path, state: str, shop="", resource="", error="") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "state": state,
        "shop": shop,
        "resource": resource,
        "at": datetime.now(UTC).isoformat(),
        "pid": os.getpid(),
    }
    if error:
        row["error"] = error
    temporary = path.with_suffix(f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(row), encoding="utf-8")
    os.replace(temporary, path)


def load_interruption_cooldown(path: Path) -> dict[str, datetime]:
    try:
        row = json.loads(path.read_text(encoding="utf-8"))
        state, label = row["state"], row["shop"]
        when = datetime.fromisoformat(row["at"])
    except (OSError, KeyError, TypeError, ValueError):
        return {}
    if (
        state not in {"capture_timeout", "sample_priority_cancelled", "failed"}
        or label
        not in {
            "local",
            "cross-border-3",
            "cross-border-4",
            "cross-border-7",
            "cross-border-12",
        }
        or when.tzinfo is None
    ):
        return {}
    retry_after = when.astimezone(UTC) + timedelta(
        minutes=30 if state in {"capture_timeout", "failed"} else 10
    )
    return {label: retry_after} if retry_after > datetime.now(UTC) else {}


@contextmanager
def process_lock(path: Path):
    if os.name != "nt":
        raise RuntimeError("Local XLSX capture requires Windows")
    import msvcrt

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as lock_file:
        if lock_file.tell() == 0:
            lock_file.write(b"0")
            lock_file.flush()
        lock_file.seek(0)
        try:
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as error:
            raise RuntimeError("Affiliate XLSX collector already running") from error
        try:
            yield
        finally:
            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
