"""Capture only missing five-shop TikTok XLSX windows after sample rounds."""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from backend.app.services.windows_background_process import background_process_options
from scripts.affiliate_export_runtime_state import (
    load_interruption_cooldown,
    process_lock,
    write_status,
)
from scripts.local_capture_guard import browser_work, pause_reason
from scripts.run_local_affiliate_dates import sample_idle_status
from scripts.run_local_affiliate_heartbeat import ZINIAO_PLATFORM_SHOP_ID
from scripts.run_remote_sample_capture_loop import SHOPS as HUBSTUDIO_SHOPS
from scripts.sample_capture_priority import refresh_official_free, run_secondary
from scripts.sample_watch_freshness import SHOPS as ERP_SHOPS
from scripts.send_local_affiliate_export import run as send_export

ROOT = Path(__file__).resolve().parents[1]
PLANNER = ROOT / "scripts" / "plan_daily_affiliate_exports.py"
LABELS = {
    "跨境3": "cross-border-3",
    "跨境4": "cross-border-4",
    "跨境7": "cross-border-7",
    "跨境12": "cross-border-12",
    "本土店": "local",
}


def fetch_plan() -> dict:
    command = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=8",
        "erp-ecs",
        "docker exec -i erp-ecs-daily-valid-creator-sync-1 python -",
    ]
    result = subprocess.run(
        command,
        input=PLANNER.read_bytes(),
        capture_output=True,
        timeout=30,
        check=False,
        **background_process_options(),
    )
    if result.returncode:
        raise RuntimeError("ECS read-only export planner failed")
    plan = json.loads(result.stdout)
    generated = datetime.fromisoformat(plan["generated_at"]).astimezone(UTC)
    if not timedelta(0) <= datetime.now(UTC) - generated <= timedelta(minutes=2):
        raise RuntimeError("ECS export plan is stale")
    shops = plan["shops"]
    if len(shops) != 5 or {item["business_name"] for item in shops} != set(LABELS):
        raise RuntimeError("ECS export plan does not contain the exact five shops")
    for shop in shops:
        label = LABELS[shop["business_name"]]
        if str(ERP_SHOPS[label]) != shop["shop_id"]:
            raise RuntimeError("ECS export plan shop identity differs from local")
    return plan


def choose_window(plan: dict, args) -> tuple[dict, dict, str] | None:
    if not plan["window_open"] and not getattr(args, "recover_missed_window", False):
        return None
    for shop in plan["shops"]:
        label = LABELS[shop["business_name"]]
        if pause_reason(label):
            continue
        if args.shop_label and args.shop_label != label:
            continue
        if getattr(args, "shop_cooldowns", {}).get(
            label, datetime.min.replace(tzinfo=UTC)
        ) > datetime.now(UTC):
            continue
        if not shop["health_ready"] or not shop["sample_released"]:
            continue
        if sample_idle_status(args.sample_status_dir, label, require_recent=False) is None:
            continue
        for window in shop["missing"]:
            key = (label, window["resource"], window["start"], window["end"])
            if getattr(args, "cooldowns", {}).get(
                key, datetime.min.replace(tzinfo=UTC)
            ) > datetime.now(UTC):
                continue
            evidence = shop["cutoffs"].get(window["resource"])
            if evidence is None or evidence["date"] < window["end"]:
                continue
            observed = datetime.fromisoformat(evidence["observed_at"]).astimezone(UTC)
            if datetime.now(UTC) - observed > timedelta(hours=6):
                continue
            return shop, window, label
    return None


def export_args(args, shop: dict, window: dict, label: str) -> argparse.Namespace:
    if label == "local":
        browser_provider = "ziniao"
        environment_id = None
        platform_shop_id = ZINIAO_PLATFORM_SHOP_ID
    else:
        browser_provider = "hubstudio"
        shop_id, environment_id, platform_shop_id = HUBSTUDIO_SHOPS[label]
        if shop_id != shop["shop_id"]:
            raise RuntimeError("HubStudio shop identity mismatch")
    return argparse.Namespace(
        shop_id=UUID(shop["shop_id"]),
        environment_id=environment_id,
        browser_provider=browser_provider,
        platform_shop_id=platform_shop_id,
        shop_timezone=shop["timezone"],
        currency=shop["currency"],
        resource=window["resource"],
        window_start=datetime.fromisoformat(window["start"]).date(),
        window_end=datetime.fromisoformat(window["end"]).date(),
        cdp_url=None,
        approved_page_target_id=getattr(args, "approved_page_target_id", None),
        capture=True,
        exclude_missing_accounts=window["resource"] == "creators",
        verify_capture_id=None,
        spool_dir=args.spool_root
        / label
        / window["resource"]
        / (window["start"] + "_" + window["end"]),
        progress_file=args.spool_root
        / label
        / window["resource"]
        / (window["start"] + "_" + window["end"])
        / "progress.json",
        token_file=args.token_file,
        api_url="https://example.invalid/configure-resource",
    )


async def execute_window(args, shop: dict, window: dict, label: str) -> str:
    options = export_args(args, shop, window, label)
    stored = list(options.spool_dir.glob("stored-*/manifest.json"))
    if stored:
        raise RuntimeError(
            "Stored XLSX still appears missing in RDS; investigate first"
        )
    pending = list(options.spool_dir.glob("pending-*/manifest.json"))
    if len(pending) > 1:
        raise RuntimeError("Multiple pending XLSX captures need reconciliation")
    options.capture = not pending
    before = sample_idle_status(
        args.sample_status_dir, label, require_recent=False
    )
    if before is None:
        return "sample_priority_wait"
    task = asyncio.create_task(send_export(options))
    deadline = asyncio.get_running_loop().time() + args.capture_timeout
    try:
        while not task.done():
            sample_changed = (
                sample_idle_status(args.sample_status_dir, label, require_recent=False)
                != before
            )
            timed_out = asyncio.get_running_loop().time() >= deadline
            if sample_changed or timed_out:
                return (
                    "sample_priority_cancelled" if sample_changed else "capture_timeout"
                )
            await asyncio.sleep(2)
        await task
        return "stored"
    finally:
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


async def run_pass(args) -> str:
    args.current_shop = ""
    args.current_resource = ""
    args.current_window = None
    plan = await asyncio.to_thread(fetch_plan)
    selected = choose_window(plan, args)
    if selected is None:
        write_status(args.status_file, "no_eligible_gap")
        return "no_eligible_gap"
    shop, window, label = selected
    args.current_shop = label
    args.current_resource = window["resource"]
    args.current_window = (label, window["resource"], window["start"], window["end"])
    if args.dry_run:
        write_status(args.status_file, "dry_run_due", label, window["resource"])
        return (
            f"dry_run_due shop={label} resource={window['resource']} "
            f"window={window['start']}..{window['end']}"
        )
    write_status(args.status_file, "capturing", label, window["resource"])
    if label == "local":
        await asyncio.to_thread(refresh_official_free)
    with browser_work(label):
        result = await run_secondary(
            label, lambda: execute_window(args, shop, window, label)
        )
    write_status(args.status_file, result, label, window["resource"])
    return result


async def run(args) -> None:
    args.cooldowns = {}
    args.shop_cooldowns = load_interruption_cooldown(args.status_file)
    while True:
        try:
            result = await run_pass(args)
            if (
                result in {"capture_timeout", "sample_priority_cancelled"}
                and args.current_window is not None
            ):
                minutes = 30 if result == "capture_timeout" else 10
                retry_after = datetime.now(UTC) + timedelta(minutes=minutes)
                args.cooldowns[args.current_window] = retry_after
                if getattr(args, "current_shop", ""):
                    args.shop_cooldowns[args.current_shop] = retry_after
            print(f"AUTO_AFFILIATE_EXPORT {result}", flush=True)
        except Exception as error:
            if args.current_window is not None:
                retry_after = datetime.now(UTC) + timedelta(minutes=30)
                args.cooldowns[args.current_window] = retry_after
                if args.current_shop:
                    args.shop_cooldowns[args.current_shop] = retry_after
            write_status(
                args.status_file,
                "failed",
                args.current_shop,
                args.current_resource,
                type(error).__name__,
            )
            print(
                f"AUTO_AFFILIATE_EXPORT_FAILED type={type(error).__name__}", flush=True
            )
            if args.once:
                raise
        if args.once:
            return
        await asyncio.sleep(args.interval_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--shop-label", choices=tuple(LABELS.values()))
    parser.add_argument(
        "--sample-status-dir",
        type=Path,
        default=ROOT / ".runtime/remote-sample-captures",
    )
    parser.add_argument(
        "--spool-root", type=Path, default=ROOT / ".runtime/affiliate-auto-export"
    )
    parser.add_argument(
        "--status-file",
        type=Path,
        default=ROOT / ".runtime/affiliate-auto-export/status.json",
    )
    parser.add_argument("--interval-seconds", type=float, default=60)
    parser.add_argument("--capture-timeout", type=float, default=480)
    parser.add_argument("--once", action="store_true")
    parser.add_argument(
        "--recover-missed-window", action="store_true",
        help="Explicit one-pass recovery outside the daily time window; all safety gates remain",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.recover_missed_window and not args.once:
        parser.error("Explicit missed-window recovery requires --once")
    if args.interval_seconds < 30 or args.capture_timeout < 30:
        parser.error("Intervals must be at least 30 seconds")
    with process_lock(args.spool_root / "collector.lock"):
        asyncio.run(run(args))


if __name__ == "__main__":
    main()
