"""Bounded recovery of the three audited video gaps, always sample-first."""

import argparse
import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

from scripts.recover_missing_affiliate_window import run as recover
from scripts.run_auto_affiliate_exports import ROOT, choose_window, fetch_plan

LABELS = ("cross-border-3", "cross-border-7", "cross-border-12")


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--token-file", type=Path, required=True)
    args = parser.parse_args()
    args.sample_status_dir = ROOT / ".runtime/remote-sample-captures"
    args.spool_root = ROOT / ".runtime/affiliate-auto-export"
    args.capture_timeout = 480
    args.apply = True
    failures = {label: 0 for label in LABELS}
    deadline = datetime.now(UTC) + timedelta(minutes=15)
    while datetime.now(UTC) < deadline:
        plan = await asyncio.to_thread(fetch_plan)
        if plan["window_open"]:
            print("VIDEO_GAP_RECOVERY_DEFERRED_TO_SCHEDULE", flush=True)
            return
        pending = [shop for shop in plan["shops"] if any(
            item["resource"] == "videos" and item["start"] == "2026-10-09"
            and item["end"] == "2026-10-10" for item in shop["missing"])]
        if not pending:
            print("AUDITED_VIDEO_GAPS_COMPLETE=True", flush=True)
            return
        attempted = False
        for label in LABELS:
            if failures[label] >= 2:
                continue
            args.shop_label = label
            selected = choose_window({**plan, "window_open": True}, args)
            if selected is None:
                continue
            window = selected[1]
            if (window["resource"], window["start"], window["end"]) != (
                "videos", "2026-10-09", "2026-10-10"
            ):
                continue
            attempted = True
            try:
                await recover(args)
            except Exception as error:  # noqa: BLE001 -- preserve other shops; print only safe type
                failures[label] += 1
                print(f"VIDEO_GAP_RECOVERY_DEFERRED shop={label} type={type(error).__name__}", flush=True)
            break  # One browser at a time; refresh admission before the next.
        if not attempted:
            print("VIDEO_GAP_RECOVERY_WAITING_SAMPLE_IDLE=True", flush=True)
        await asyncio.sleep(10)
    print("VIDEO_GAP_RECOVERY_TIME_LIMIT_REACHED=True", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
