"""Recover one exact missing XLSX window after the ordinary schedule closes."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from scripts.local_capture_guard import browser_work
from scripts.run_auto_affiliate_exports import (
    ROOT,
    choose_window,
    execute_window,
    fetch_plan,
)
from scripts.sample_capture_priority import refresh_official_free, run_secondary


async def run(args: argparse.Namespace) -> None:
    plan = await asyncio.to_thread(fetch_plan)
    if plan["window_open"]:
        raise RuntimeError("Ordinary export scheduler owns the open window")
    selected = choose_window({**plan, "window_open": True}, args)
    if selected is None:
        print(f"AFFILIATE_RECOVERY_NOT_READY shop={args.shop_label}")
        return
    shop, window, label = selected
    print(
        f"AFFILIATE_RECOVERY_PLAN shop={label} "
        f"resource={window['resource']} "
        f"start={window['start']} end={window['end']}",
        flush=True,
    )
    if not args.apply:
        return
    if label == "local":
        await asyncio.to_thread(refresh_official_free)
    with browser_work(label):
        result = await run_secondary(
            label, lambda: execute_window(args, shop, window, label)
        )
    print(f"AFFILIATE_RECOVERY_RESULT shop={label} state={result}", flush=True)
    if result == "stored":
        refreshed = await asyncio.to_thread(fetch_plan)
        target = next(
            item for item in refreshed["shops"] if item["shop_id"] == shop["shop_id"]
        )
        if window in target["missing"]:
            raise RuntimeError("Stored XLSX window remains missing after readback")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shop-label", choices=("local", "cross-border-3", "cross-border-4", "cross-border-7", "cross-border-12"), required=True)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--approved-page-target-id")
    args = parser.parse_args()
    args.sample_status_dir = ROOT / ".runtime/remote-sample-captures"
    args.spool_root = ROOT / ".runtime/affiliate-auto-export"
    args.capture_timeout = 480
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
