"""Report verified TK creator/video dates only in sample-idle windows."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

if os.name == "nt" and sys.version_info >= (3, 13):
    import platform

    platform._wmi = None  # type: ignore[attr-defined]

from backend.app.services.hubstudio_cdp import discover_hubstudio_cdp_url
from scripts.local_capture_guard import browser_work, ensure_browser_ready
from scripts.probe_daily_valid_creator_online import probe_shop
from scripts.probe_ziniao_affiliate_dates import probe as probe_ziniao
from scripts.run_local_affiliate_heartbeat import ZINIAO_PLATFORM_SHOP_ID
from scripts.run_remote_sample_capture_loop import SHOPS as HUBSTUDIO_SHOPS
from scripts.sample_capture_priority import refresh_official_free, run_secondary
from scripts.sample_watch_freshness import SHOPS as ERP_SHOPS

BUSINESS_NAMES = {
    "cross-border-3": "跨境3",
    "cross-border-4": "跨境4",
    "cross-border-7": "跨境7",
    "cross-border-12": "跨境12",
    "local": "本土店",
}
PROBE_INTERVAL = timedelta(hours=2)
SAMPLE_IDLE_WINDOW = timedelta(seconds=60)


def sample_idle_status(
    status_dir: Path, shop_label: str, *, require_recent: bool = True
) -> str | None:
    if shop_label == "local":
        return "server_official_api"
    path = status_dir / f"{shop_label}.status.json"
    try:
        status = json.loads(path.read_text(encoding="utf-8"))
        updated = datetime.fromisoformat(status["at"]).astimezone(UTC)
    except (OSError, KeyError, TypeError, ValueError):
        return None
    age = datetime.now(UTC) - updated
    if status.get("state") != "stored" or age < timedelta(0):
        return None
    if require_recent and age > SAMPLE_IDLE_WINDOW:
        return None
    return status["at"]


def recent_success(status_dir: Path, shop_label: str) -> bool:
    path = status_dir / f"{shop_label}.status.json"
    try:
        status = json.loads(path.read_text(encoding="utf-8"))
        observed = datetime.fromisoformat(status["observed_at"]).astimezone(UTC)
    except (OSError, KeyError, TypeError, ValueError):
        return False
    return (
        status.get("state") == "stored"
        and timedelta(0) <= datetime.now(UTC) - observed < PROBE_INTERVAL
    )


def failure_cooldown(status_dir: Path, shop_label: str) -> bool:
    path = status_dir / f"{shop_label}.status.json"
    try:
        status = json.loads(path.read_text(encoding="utf-8"))
        updated = datetime.fromisoformat(status["at"]).astimezone(UTC)
    except (OSError, KeyError, TypeError, ValueError):
        return False
    return status.get("state") == "failed" and timedelta(0) <= datetime.now(
        UTC
    ) - updated < timedelta(minutes=3)


async def probe_direct_dates(shop_label: str) -> dict[str, str]:
    if shop_label == "local":
        row = await probe_ziniao()
    else:
        _shop_id, _environment_id, platform_shop_id = HUBSTUDIO_SHOPS[shop_label]
        cdp_url = await discover_hubstudio_cdp_url(
            current_url=None, expected_platform_shop_id=platform_shop_id
        )
        if cdp_url is None:
            raise RuntimeError("Verified shop CDP is unavailable")
        await ensure_browser_ready(shop_label, cdp_url)
        row = await probe_shop(BUSINESS_NAMES[shop_label], platform_shop_id, cdp_url)
    if row.get("shop") != BUSINESS_NAMES[shop_label] or not all(
        row.get(resource) for resource in ("creators", "videos")
    ):
        raise RuntimeError("Direct TK date evidence is incomplete")
    return row


async def send_dates(client, args, token: str, shop_label: str, row: dict) -> None:
    platform_shop_id = (
        ZINIAO_PLATFORM_SHOP_ID
        if shop_label == "local"
        else HUBSTUDIO_SHOPS[shop_label][2]
    )
    response = await client.post(
        args.api_url,
        headers={"x-erp-affiliate-capture-token": token},
        json={
            "shop_id": str(ERP_SHOPS[shop_label]),
            "platform_shop_id": platform_shop_id,
            "state": "online",
            "observed_at": datetime.now(UTC).isoformat(),
            "dates": [
                {
                    "resource": resource,
                    "latest_available_date": row[resource],
                    "observed_at": row["observed_at"],
                }
                for resource in ("creators", "videos")
            ],
        },
    )
    if response.status_code != 202 or response.json().get("status") != "stored":
        raise RuntimeError(f"ECS rejected direct TK dates: HTTP {response.status_code}")


def write_status(directory: Path, shop_label: str, state: str, row=None, error=""):
    directory.mkdir(parents=True, exist_ok=True)
    status = {
        "shop": shop_label,
        "state": state,
        "at": datetime.now(UTC).isoformat(),
        "pid": os.getpid(),
    }
    if row:
        status.update(
            observed_at=row["observed_at"],
            creators=row["creators"],
            videos=row["videos"],
        )
    if error:
        status["error"] = error
    target = directory / f"{shop_label}.status.json"
    temporary = directory / f"{shop_label}.{os.getpid()}.tmp"
    temporary.write_text(json.dumps(status), encoding="utf-8")
    os.replace(temporary, target)


async def run_pass(args, client, token: str) -> int:
    labels = (args.shop_label,) if args.shop_label else tuple(BUSINESS_NAMES)
    stored = 0
    for shop_label in labels:
        if recent_success(args.status_dir, shop_label):
            continue
        if failure_cooldown(args.status_dir, shop_label):
            continue
        before = sample_idle_status(args.sample_status_dir, shop_label)
        if before is None:
            continue
        try:
            if shop_label == "local":
                await asyncio.to_thread(refresh_official_free)
            with browser_work(shop_label):
                row = await run_secondary(
                    shop_label, lambda label=shop_label: probe_direct_dates(label)
                )
            after = sample_idle_status(
                args.sample_status_dir, shop_label, require_recent=False
            )
            if before != after:
                continue
            await send_dates(client, args, token, shop_label, row)
            write_status(args.status_dir, shop_label, "stored", row)
            stored += 1
        except Exception as error:
            write_status(
                args.status_dir, shop_label, "failed", error=type(error).__name__
            )
            print(
                f"AFFILIATE_DATES_FAILED shop={shop_label} "
                f"error={type(error).__name__}",
                flush=True,
            )
            if args.once:
                raise
    return stored


async def run(args) -> None:
    token = args.token_file.read_text(encoding="utf-8").strip()
    if len(token) < 32:
        raise RuntimeError("Affiliate capture token file is unavailable")
    async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
        while True:
            stored = await run_pass(args, client, token)
            if args.once:
                print(f"DIRECT_DATES_STORED={stored}")
                return
            await asyncio.sleep(args.interval_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shop-label", choices=BUSINESS_NAMES)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval-seconds", type=float, default=30)
    parser.add_argument(
        "--status-dir", type=Path, default=Path(".runtime/remote-affiliate-dates")
    )
    parser.add_argument(
        "--sample-status-dir",
        type=Path,
        default=Path(".runtime/remote-sample-captures"),
    )
    parser.add_argument(
        "--api-url",
        default="https://example.invalid/configure-resource",
    )
    args = parser.parse_args()
    if not args.api_url.startswith("https://") or args.interval_seconds <= 0:
        parser.error("HTTPS and a positive interval are required")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
