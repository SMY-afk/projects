"""Bounded one-window-at-a-time recovery without taking sample priority."""

from __future__ import annotations

import argparse
import asyncio
from collections import deque
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import monotonic

from scripts.affiliate_export_runtime_state import process_lock
from scripts.local_capture_guard import CaptureGuardError, pause_reason
from scripts.recover_missing_affiliate_window import run as recover_one
from scripts.run_auto_affiliate_exports import LABELS, ROOT, fetch_plan
from scripts.run_local_affiliate_dates import sample_idle_status
from scripts.sample_capture_priority import secondary_budget


async def run(args: argparse.Namespace) -> None:
    labels = deque(label for label in LABELS.values() if label != "local")
    cooldowns: dict[str, datetime] = {}
    deadline = monotonic() + args.max_minutes * 60
    while monotonic() < deadline:
        plan = await asyncio.to_thread(fetch_plan)
        if plan["window_open"]:
            print("AFFILIATE_RECOVERY_STOP normal_window_open", flush=True)
            return
        missing = {
            LABELS[shop["business_name"]]: len(shop["missing"])
            for shop in plan["shops"]
        }
        print(f"AFFILIATE_RECOVERY_REMAINING {missing}", flush=True)
        if not any(missing.values()):
            print("AFFILIATE_RECOVERY_COMPLETE", flush=True)
            return
        selected = None
        for _ in range(len(labels)):
            label = labels[0]
            labels.rotate(-1)
            if (
                missing.get(label, 0)
                and not pause_reason(label)
                and cooldowns.get(label, datetime.min.replace(tzinfo=UTC))
                <= datetime.now(UTC)
                and secondary_budget(label) > 0
                and sample_idle_status(
                    args.sample_status_dir, label, require_recent=False
                ) is not None
            ):
                selected = label
                break
        if selected is None:
            await asyncio.sleep(20)
            continue
        args.shop_label = selected
        try:
            await recover_one(args)
        except CaptureGuardError as error:
            print(
                f"AFFILIATE_RECOVERY_DEFER shop={selected} code={error.code}",
                flush=True,
            )
        except Exception as error:  # noqa: BLE001 -- isolate one failed shop
            cooldowns[selected] = datetime.now(UTC) + timedelta(minutes=10)
            print(
                f"AFFILIATE_RECOVERY_FAILED shop={selected} "
                f"type={type(error).__name__}",
                flush=True,
            )
        await asyncio.sleep(10)
    print("AFFILIATE_RECOVERY_STOP time_budget", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--max-minutes", type=int, default=90)
    args = parser.parse_args()
    if not 1 <= args.max_minutes <= 90:
        parser.error("Recovery is limited to 1–90 minutes")
    args.sample_status_dir = ROOT / ".runtime/remote-sample-captures"
    args.spool_root = ROOT / ".runtime/affiliate-auto-export"
    args.capture_timeout = 480
    args.apply = True
    with process_lock(args.spool_root / "recovery.lock"):
        asyncio.run(run(args))


if __name__ == "__main__":
    main()
