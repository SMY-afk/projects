"""Recover an explicitly audited Cross12 window without blocking sample rounds."""

import argparse
import asyncio
from pathlib import Path

from scripts.local_capture_guard import browser_work
from scripts.run_auto_affiliate_exports import ROOT, choose_window, execute_window, fetch_plan
from scripts.sample_capture_priority import run_secondary

LABEL = "cross-border-12"
WINDOWS = {
    "videos": {"resource": "videos", "start": "2026-10-09", "end": "2026-10-10"},
    "creators": {"resource": "creators", "start": "2026-10-11", "end": "2026-10-12"},
}


async def run(args):
    required = WINDOWS[args.resource]
    plan = await asyncio.to_thread(fetch_plan)
    if plan["window_open"]:
        raise RuntimeError("Normal export scheduler owns the open window")
    filtered = {**plan, "window_open": True, "shops": [
        {**shop, "missing": [window for window in shop["missing"]
                             if all(window.get(key) == value for key, value in required.items())]}
        for shop in plan["shops"]
    ]}
    selected = choose_window(filtered, args)
    if selected is None:
        print(f"CROSS12_GAP_NOT_READY_OR_COMPLETE resource={args.resource}", flush=True)
        return
    shop, window, label = selected
    if label != LABEL or shop["shop_id"] != "5e1fed24-8268-5b5a-9ead-5efb862e7a51":
        raise RuntimeError("Unexpected Cross12 gap identity")
    with browser_work(label):
        result = await run_secondary(label, lambda: execute_window(args, shop, window, label))
    print(f"CROSS12_GAP_RESULT resource={args.resource} state={result}", flush=True)
    if result == "stored":
        refreshed = await asyncio.to_thread(fetch_plan)
        target = next(item for item in refreshed["shops"] if item["shop_id"] == shop["shop_id"])
        if window in target["missing"]:
            raise RuntimeError("Audited gap remains missing after source readback")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resource", choices=tuple(WINDOWS), default="videos")
    parser.add_argument("--token-file", type=Path, required=True)
    args = parser.parse_args()
    args.shop_label = LABEL
    args.sample_status_dir = ROOT / ".runtime/remote-sample-captures"
    args.spool_root = ROOT / ".runtime/affiliate-auto-export"
    args.capture_timeout = 480
    asyncio.run(run(args))
