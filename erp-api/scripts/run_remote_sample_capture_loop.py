"""Capture one verified HubStudio shop to ECS, without local DB writes."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import traceback
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import monotonic
from uuid import UUID

if os.name == "nt" and sys.version_info >= (3, 13):
    import platform

    platform._wmi = None  # type: ignore[attr-defined]

from backend.app.services.hubstudio_cdp import discover_hubstudio_cdp_url
from backend.app.services.sample_raw_batch_store import SampleRawBatchStore
from backend.app.services.sample_raw_capture_retry import recover_fresh_completed
from scripts.local_capture_guard import (
    browser_work,
    ensure_browser_ready,
    retry_delay,
    security_reason,
)
from scripts.sample_capture_priority import (
    finish_free,
    initial_free_delay,
    request_free,
)
from scripts.send_local_sample_capture import run as send_batch

SHOPS = {
    "cross-border-3": (
        "eb7678c2-67d6-5446-85f0-dc8fba9b75d6",
        "802623795",
        "9622543325839925006",
    ),
    "cross-border-4": (
        "50770999-40ce-5b84-bb01-13701932bdf1",
        "917845896",
        "9768147009521852682",
    ),
    "cross-border-7": (
        "fe629cb8-fa7b-56a5-970c-2f6e9ebc5703",
        "1222553679",
        "9121478993551097445",
    ),
    "cross-border-12": (
        "5e1fed24-8268-5b5a-9ead-5efb862e7a51",
        "1489885983",
        "9472478445887813622",
    ),
}


async def cycle(args: argparse.Namespace) -> None:
    shop_id, environment_id, platform_shop_id = SHOPS[args.shop_label]
    store = SampleRawBatchStore(args.spool_root, shop_id)
    pending = await asyncio.to_thread(recover_fresh_completed, store)
    cdp_url = None
    if pending is None:
        cdp_url = await discover_hubstudio_cdp_url(
            current_url=getattr(args, "verified_cdp_url", None),
            expected_platform_shop_id=platform_shop_id,
        )
        if cdp_url is None:
            raise RuntimeError("verified_shop_browser_unavailable")
        await ensure_browser_ready(args.shop_label, cdp_url)
        args.verified_cdp_url = cdp_url
    await send_batch(
        argparse.Namespace(
            shop_id=UUID(shop_id),
            environment_id=environment_id,
            platform_shop_id=platform_shop_id,
            cdp_url=cdp_url,
            capture=pending is None,
            verify_batch_sequence=None,
            capture_timeout=args.capture_timeout,
            spool_root=args.spool_root,
            token_file=args.token_file,
            api_url=args.api_url,
            processing_mode=args.processing_mode,
        )
    )


async def run(args: argparse.Namespace) -> None:
    _write_status(args.status_dir, args.shop_label, "starting")
    if not args.once:
        delay = initial_free_delay(args.shop_label, args.interval_seconds)
        if delay:
            _write_status(args.status_dir, args.shop_label, "idle")
            await asyncio.sleep(delay)
    failures = 0
    while True:
        started = monotonic()
        started_at = datetime.now(UTC)
        interval = args.interval_seconds
        succeeded = False
        request_free(args.shop_label)
        _write_status(args.status_dir, args.shop_label, "capturing")
        try:
            with browser_work(args.shop_label):
                await cycle(args)
            failures = 0
            succeeded = True
            _write_status(args.status_dir, args.shop_label, "stored")
        except Exception as error:
            failures += 1
            interval = retry_delay(error, failures, args.interval_seconds)
            _write_status(
                args.status_dir,
                args.shop_label,
                "failed",
                type(error).__name__,
                getattr(error, "code", None) or security_reason(error),
            )
            print(
                f"REMOTE_SAMPLE_CYCLE_FAILED shop={args.shop_label} "
                f"error={type(error).__name__}",
                flush=True,
            )
            if args.once:
                raise
        finally:
            finish_free(
                args.shop_label,
                succeeded,
                started_at
                + timedelta(seconds=max(interval, monotonic() - started + 1)),
            )
        if args.once:
            return
        await asyncio.sleep(max(1, interval - (monotonic() - started)))


def _write_status(
    directory: Path,
    shop_label: str,
    state: str,
    error: str | None = None,
    code: str | None = None,
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    payload = {
        "shop": shop_label,
        "state": state,
        "at": datetime.now(UTC).isoformat(),
        "pid": os.getpid(),
    }
    if shop_label == "cross-border-7" or shop_label.startswith("cross-border-7-"):
        payload["collector_version"] = "cross7-reused-review-sort-visible-v6"
    elif shop_label == "cross-border-4":
        payload["collector_version"] = "cross4-unique-free-tab-v1"
    elif shop_label == "cross-border-3":
        payload["collector_version"] = "cross3-first-page-full-window-v2"
    target = directory / f"{shop_label}.status.json"
    try:
        previous = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        previous = {}
    if previous.get("last_success_at"):
        payload["last_success_at"] = previous["last_success_at"]
    if state == "stored":
        payload["last_success_at"] = payload["at"]
    if error:
        payload["error"] = error
        current = sys.exc_info()[1]
        if current is not None:
            frames = traceback.extract_tb(current.__traceback__)
            root = Path(__file__).resolve().parents[1]
            prefixes = tuple(str(root / folder).casefold() + os.sep
                             for folder in ("backend", "scripts", "src", ".runtime", "tests"))
            local_frames = [frame for frame in frames if frame.filename.casefold().startswith(prefixes)]
            payload["failure_frames"] = [
                f"{Path(frame.filename).name}:{frame.name}:{frame.lineno}"
                for frame in (local_frames or frames)[-5:]
            ]
            if not code and "strict mode violation" in str(current).casefold():
                code = "page_control_ambiguous"
    if code:
        payload["error_code"] = code
    temporary = directory / f"{shop_label}.{os.getpid()}.tmp"
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, target)


@contextmanager
def shop_process_lock(spool_root: Path, shop_label: str):
    if os.name != "nt":
        raise RuntimeError("This local collector requires Windows")
    import msvcrt

    spool_root.mkdir(parents=True, exist_ok=True)
    with (spool_root / f"{shop_label}.lock").open("a+b") as lock_file:
        if lock_file.tell() == 0:
            lock_file.write(b"0")
            lock_file.flush()
        lock_file.seek(0)
        try:
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as error:
            raise RuntimeError("sample_collector_already_running") from error
        try:
            yield
        finally:
            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shop-label", choices=SHOPS, required=True)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument(
        "--spool-root", type=Path, default=Path(".runtime/sample-raw-queue")
    )
    parser.add_argument(
        "--status-dir", type=Path, default=Path(".runtime/remote-sample-captures")
    )
    parser.add_argument(
        "--api-url",
        default="https://example.invalid/configure-resource",
    )
    parser.add_argument("--interval-seconds", type=float, default=300)
    parser.add_argument("--capture-timeout", type=float, default=240)
    parser.add_argument(
        "--processing-mode", choices=("defer", "enqueue"), default="defer"
    )
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if not args.api_url.startswith("https://") or args.interval_seconds <= 0:
        parser.error("HTTPS and a positive interval are required")
    with shop_process_lock(args.spool_root, args.shop_label):
        asyncio.run(run(args))


if __name__ == "__main__":
    main()
