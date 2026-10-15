"""Separate refundable collectors leave existing free collection unchanged."""

import argparse
import asyncio
import json
import os
import sys
import traceback
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import monotonic
from types import SimpleNamespace
from uuid import UUID

from backend.app.services.hubstudio_cdp import (
    discover_hubstudio_cdp_url,
    read_cdp_platform_shop_ids,
)
from backend.app.services.hubstudio_cdp_ownership import assert_erp_hubstudio_cdp_url
from backend.app.services.local_refundable_page_guard import OWNED_PAGE_FAILURE_CODES
from backend.app.services.refundable_sample_capture import (
    capture_refundable_status,
    refundable_store,
)
from scripts.local_capture_guard import (
    browser_work,
    ensure_browser_ready,
    retry_delay,
    security_reason,
)
from scripts.local_paid_readiness import ensure_local_paid_ready
from scripts.paid_browser_capacity import wait_for_browser_capacity
from scripts.paid_window_schedule import wait_for_free_window
from scripts.run_local_affiliate_heartbeat import ZINIAO_PLATFORM_SHOP_ID
from scripts.run_remote_sample_capture_loop import (
    SHOPS,
    shop_process_lock,
)
from scripts.run_remote_sample_capture_loop import (
    _write_status as _base_status,
)
from scripts.sample_capture_priority import (
    finish_paid_retry,
    mark_attempt,
    mark_paid_retry,
    refresh_official_free,
    run_secondary,
    secondary_budget,
    select_paid_tab,
)
from scripts.send_local_sample_capture import CaptureIngressError
from scripts.send_local_sample_capture import run as send_batch
from scripts.ziniao_affiliate_export_source import resolve_ziniao_export_source


def _write_status(directory, label, state, error=None, code=None):
    _base_status(directory, label, state, error, code)
    path = directory / f"{label}.status.json"
    row = json.loads(path.read_text(encoding="utf-8"))
    row["collector_version"] = "paid-local-owned-ready-live-identity-v17" if label.split("-")[0] == "local" else "paid-free-window-adaptive-profile-budget-v15"
    current = sys.exc_info()[1]
    if error and current is not None:
        row["failure_frames"] = [
            f"{Path(frame.filename).name}:{frame.name}:{frame.lineno}"
            for frame in traceback.extract_tb(current.__traceback__)[-5:]
        ]
    temporary = path.with_suffix(f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(row), encoding="utf-8")
    os.replace(temporary, path)


def failure_code(error):
    code = getattr(error, "code", None) or security_reason(error)
    if code:
        return code
    message = str(error).casefold()
    if message in OWNED_PAGE_FAILURE_CODES:
        return message
    if "strict mode violation" in message:
        return "page_control_ambiguous"
    if "status tab is missing" in message:
        return "status_tab_unavailable"
    if "refundable stable identity" in message:
        return "source_identity_invalid"
    if "timeout" in type(error).__name__.casefold():
        return "page_control_timeout"
    return "capture_failed"


async def cycle(args):
    selected = select_paid_tab(args)
    if selected is None:
        return False
    if args.shop_label == "local":
        shop_id = "6fdc5cdc-90da-5524-82f7-9b11746c5e10"
        platform_id = ZINIAO_PLATFORM_SHOP_ID
        endpoint, environment_id = await resolve_ziniao_export_source(platform_id)
        host = "affiliate-us.tiktok.com"
    else:
        shop_id, environment_id, platform_id = SHOPS[args.shop_label]
        endpoint = await discover_hubstudio_cdp_url(
            current_url=getattr(args, "verified_cdp_url", None),
            expected_platform_shop_id=platform_id,
        )
        if endpoint is None:
            raise RuntimeError("Verified refundable browser is unavailable")
        assert_erp_hubstudio_cdp_url(endpoint)
        host = "affiliate.tiktokshopglobalselling.com"
    if await read_cdp_platform_shop_ids(endpoint) != frozenset({platform_id}):
        raise RuntimeError("Refundable browser shop identity changed")
    await (ensure_local_paid_ready(endpoint) if args.shop_label == "local" else ensure_browser_ready(args.shop_label, endpoint))
    args.verified_cdp_url = endpoint
    for tab_type in (selected,):
        mark_attempt(args, tab_type)
        store = refundable_store(args.spool_root, shop_id, tab_type)
        _write_status(args.status_dir, args.shop_label, "capturing")
        _write_status(args.status_dir, f"{args.shop_label}-{tab_type}", "capturing")
        try:
            batch = await asyncio.wait_for(
                capture_refundable_status(
                    endpoint, platform_id, store, tab_type, timeout=60, host=host
                ),
                timeout=args.capture_timeout,
            )
            if args.capture_only:
                print(
                    f"REFUNDABLE_CAPTURED shop={args.shop_label} tab={tab_type} "
                    f"pages={batch.page_count} records={batch.captured_total}",
                    flush=True,
                )
                continue
            delivery_args = SimpleNamespace(
                raw_store=store,
                sample_type="refundable",
                shop_id=UUID(shop_id),
                environment_id=environment_id,
                platform_shop_id=platform_id,
                capture=False,
                verify_batch_sequence=None,
                spool_root=args.spool_root,
                token_file=args.token_file,
                api_url=args.api_url,
                processing_mode="enqueue",
            )
            args.completed_paid_scope = (delivery_args, tab_type)
        except Exception as error:
            _write_status(
                args.status_dir,
                f"{args.shop_label}-{tab_type}",
                "failed",
                type(error).__name__,
                failure_code(error),
            )
            print(
                f"REFUNDABLE_CYCLE_FAILED shop={args.shop_label} tab={tab_type} "
                f"error={type(error).__name__}",
                flush=True,
            )
            frames = traceback.extract_tb(error.__traceback__)
            print("REFUNDABLE_FAILURE_FRAMES " + " ".join(
                f"{Path(frame.filename).name}:{frame.name}:{frame.lineno}"
                for frame in frames[-4:]
            ), flush=True)
            raise
    return True


async def deliver(args):
    """Durable HTTP retries are independent of browser priority and capacity."""
    delivery_args, tab = args.completed_paid_scope
    _write_status(args.status_dir, args.shop_label, "delivering")
    _write_status(args.status_dir, f"{args.shop_label}-{tab}", "delivering")
    for attempt in range(12):
        try:
            await send_batch(delivery_args)
            _write_status(args.status_dir, f"{args.shop_label}-{tab}", "stored")
            finish_paid_retry(args, tab)
            return
        except CaptureIngressError as error:
            if error.code not in {"busy", "queue_unavailable"} or attempt == 11:
                raise
            await asyncio.sleep(15)


def terminal_recent(args, tab_type):
    """Terminal state recexamplebda1c91a retain their existing thirty-minute cadence."""
    path = args.status_dir / f"{args.shop_label}-{tab_type}.status.json"
    try:
        row = json.loads(path.read_text(encoding="utf-8"))
        at = datetime.fromisoformat(row.get("last_success_at", row["at"]))
        return timedelta(0) <= datetime.now(UTC) - at < timedelta(minutes=30)
    except (OSError, ValueError, KeyError, TypeError):
        return False


async def run(args):
    failures = 0
    while True:
        started = monotonic()
        interval = args.interval_seconds
        waiting_for_free = False
        args.active_paid_tab = None
        args.completed_paid_scope = None
        try:
            if args.shop_label == "local":
                await asyncio.to_thread(refresh_official_free)
            captured = False
            if select_paid_tab(args) is not None:
                captured = await wait_for_browser_capacity(
                    args.shop_label,
                    lambda: run_secondary(args.shop_label, lambda: cycle(args)),
                    guard=browser_work,
                    can_wait=lambda: secondary_budget(args.shop_label) > 0,
                )
            if captured and not args.capture_only:
                await deliver(args)
            failures = 0
            _write_status(
                args.status_dir, args.shop_label, "stored" if captured else "idle"
            )
        except Exception as error:
            waiting_for_free = getattr(error, "code", None) == "free_priority_wait"
            if (
                getattr(error, "code", None)
                in {"secondary_timeout", "free_priority_wait"}
                and args.active_paid_tab is not None
            ):
                mark_paid_retry(args)
                _write_status(
                    args.status_dir,
                    f"{args.shop_label}-{args.active_paid_tab}",
                    "deferred",
                    type(error).__name__,
                    error.code,
                )
            failures += getattr(error, "code", None) != "free_priority_wait"
            interval = retry_delay(error, failures, args.interval_seconds)
            if getattr(error, "code", None) == "secondary_timeout":
                interval = 60
            _write_status(
                args.status_dir,
                args.shop_label,
                "waiting_free_window" if waiting_for_free else "deferred"
                if getattr(error, "code", None)
                in (
                    {"free_priority_wait", "browser_busy", "capture_capacity_busy",
                     "secondary_timeout"}
                )
                else "failed",
                type(error).__name__,
                failure_code(error),
            )
            print(
                f"{'REFUNDABLE_WINDOW_WAIT' if waiting_for_free else 'REFUNDABLE_SHOP_FAILED'} "
                f"shop={args.shop_label} error={type(error).__name__}",
                flush=True,
            )
            if args.once:
                raise
        if args.once:
            return
        stagger = ("local", *SHOPS).index(args.shop_label) * 5
        delay = max(1, interval + stagger - (monotonic() - started))
        if waiting_for_free and args.shop_label == "cross-border-3":
            await wait_for_free_window(args.shop_label, delay)
        else:
            await asyncio.sleep(delay)


if __name__ == "__main__":
    if os.name == "nt":
        import platform

        platform._wmi = None
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shop-label", choices=(*SHOPS, "local"), required=True)
    parser.add_argument("--token-file", type=Path)
    parser.add_argument(
        "--spool-root", type=Path, default=Path(".runtime/refundable-raw-queue")
    )
    parser.add_argument(
        "--status-dir", type=Path, default=Path(".runtime/refundable-captures")
    )
    parser.add_argument(
        "--api-url",
        default="https://example.invalid/configure-resource",
    )
    parser.add_argument("--capture-timeout", type=float, default=240)
    parser.add_argument("--interval-seconds", type=float, default=60)
    parser.add_argument("--capture-only", action="store_true")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--tabs", type=int, nargs="+", choices=range(1, 7), default=list(range(1, 7)))
    args = parser.parse_args()
    if not args.capture_only and not args.token_file:
        parser.error("--token-file is required for remote delivery")
    if not args.api_url.startswith("https://") or args.interval_seconds <= 0:
        parser.error("HTTPS and a positive interval are required")
    with shop_process_lock(args.spool_root, f"refundable-{args.shop_label}"):
        asyncio.run(run(args))
