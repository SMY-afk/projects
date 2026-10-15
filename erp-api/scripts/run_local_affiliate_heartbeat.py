"""Report exact-shop browser health to ECS without closing owned browsers."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from uuid import UUID

import httpx

from backend.app.services.local_browser_security import browser_security_state
from scripts.local_capture_guard import pause_shop

if os.name == "nt" and sys.version_info >= (3, 13):
    import platform

    platform._wmi = None  # type: ignore[attr-defined]

from backend.app.services.hubstudio_cdp import (
    discover_hubstudio_cdp_url,
    probe_cdp_endpoint,
    read_cdp_platform_shop_ids,
)
from scripts.run_remote_sample_capture_loop import SHOPS as HUBSTUDIO_SHOPS
from scripts.sample_watch_freshness import SHOPS as ERP_SHOPS
from scripts.ziniao_affiliate_export_source import resolve_ziniao_export_source

ZINIAO_PLATFORM_SHOP_ID = "9136806951995371293"
SHOP_LABELS = (*HUBSTUDIO_SHOPS, "local")


async def probe_shop(
    shop_label: str, cached_cdp_url: str | None = None
) -> tuple[str, str | None]:
    if shop_label == "local":
        platform_shop_id = ZINIAO_PLATFORM_SHOP_ID
    else:
        shop_id, _environment_id, platform_shop_id = HUBSTUDIO_SHOPS[shop_label]
        if ERP_SHOPS[shop_label] != UUID(shop_id):
            raise RuntimeError("HubStudio and ERP shop IDs differ")
    cdp_url = cached_cdp_url
    if cdp_url:
        available = await probe_cdp_endpoint(cdp_url)
        if not available:
            await asyncio.sleep(0.5)
            available = await probe_cdp_endpoint(cdp_url)
        if not available:
            return "connecting", cdp_url
    if cdp_url is None:
        if shop_label == "local":
            cdp_url, _environment_id = await resolve_ziniao_export_source(
                platform_shop_id
            )
        else:
            cdp_url = await discover_hubstudio_cdp_url(
                current_url=None, expected_platform_shop_id=platform_shop_id
            )
    if cdp_url is None:
        return "browser_offline", None
    if cached_cdp_url is None and not await probe_cdp_endpoint(cdp_url):
        return "connecting", cdp_url
    shop_ids = await read_cdp_platform_shop_ids(cdp_url)
    if not shop_ids:
        await asyncio.sleep(0.5)
        shop_ids = await read_cdp_platform_shop_ids(cdp_url)
    if not shop_ids:
        return "connecting", cdp_url
    if shop_ids != frozenset({platform_shop_id}):
        raise RuntimeError("Browser contains a missing or mixed shop identity")
    state = await asyncio.wait_for(browser_security_state(cdp_url), timeout=10)
    if state in {"captcha", "session_expired"}:
        pause_shop(shop_label, state)
    return state, cdp_url


async def probe_with_last_verified(
    shop_label: str, cached_cdp_url: str | None, last_verified_url: str | None
) -> tuple[str, str | None]:
    state, cdp_url = await probe_shop(shop_label, cached_cdp_url)
    if state == "browser_offline" and cached_cdp_url is None and last_verified_url:
        recovered, recovered_url = await probe_shop(shop_label, last_verified_url)
        if recovered == "online":
            return recovered, recovered_url
    return state, cdp_url


async def send_heartbeat(
    client: httpx.AsyncClient, url: str, token: str, shop_label: str, state: str
) -> None:
    platform_shop_id = (
        ZINIAO_PLATFORM_SHOP_ID
        if shop_label == "local"
        else HUBSTUDIO_SHOPS[shop_label][2]
    )
    response = await client.post(
        url,
        headers={"x-erp-affiliate-capture-token": token},
        json={
            "shop_id": str(ERP_SHOPS[shop_label]),
            "platform_shop_id": platform_shop_id,
            "state": state,
            "observed_at": datetime.now(UTC).isoformat(),
        },
    )
    if response.status_code != 202 or response.json().get("status") != "stored":
        raise RuntimeError(
            f"ECS rejected affiliate health: HTTP {response.status_code}"
        )


def write_status(directory: Path, shop_label: str, state: str, error: str = ""):
    directory.mkdir(parents=True, exist_ok=True)
    status = {
        "shop": shop_label,
        "state": state,
        "at": datetime.now(UTC).isoformat(),
        "pid": os.getpid(),
    }
    if error:
        status["error"] = error
    target = directory / f"{shop_label}.status.json"
    temporary = directory / f"{shop_label}.{os.getpid()}.tmp"
    temporary.write_text(json.dumps(status), encoding="utf-8")
    os.replace(temporary, target)


async def run_shop(args, client, token: str, shop_label: str) -> None:
    cached_cdp_url = None
    last_verified_url = None
    consecutive_connecting = 0
    while True:
        started = monotonic()
        try:
            state, cached_cdp_url = await probe_with_last_verified(
                shop_label, cached_cdp_url, last_verified_url
            )
            await send_heartbeat(client, args.api_url, token, shop_label, state)
            write_status(args.status_dir, shop_label, state)
            if state == "online":
                last_verified_url = cached_cdp_url
            consecutive_connecting = (
                consecutive_connecting + 1 if state == "connecting" else 0
            )
            if consecutive_connecting >= 3:
                cached_cdp_url = None
        except Exception as error:
            cached_cdp_url = None
            try:
                await send_heartbeat(
                    client, args.api_url, token, shop_label, "connecting"
                )
            except Exception:  # noqa: BLE001,S110 -- original heartbeat failure is recorded below
                pass
            write_status(args.status_dir, shop_label, "failed", type(error).__name__)
            print(
                f"AFFILIATE_HEARTBEAT_FAILED shop={shop_label} "
                f"error={type(error).__name__}",
                flush=True,
            )
            if args.once:
                raise
        if args.once:
            return
        await asyncio.sleep(max(1, args.interval_seconds - (monotonic() - started)))


async def run(args) -> None:
    token = args.token_file.read_text(encoding="utf-8").strip()
    if len(token) < 32:
        raise RuntimeError("Affiliate capture token file is unavailable")
    labels = (args.shop_label,) if args.shop_label else SHOP_LABELS
    async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
        await asyncio.gather(
            *(run_shop(args, client, token, label) for label in labels)
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shop-label", choices=SHOP_LABELS)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument(
        "--api-url",
        default="https://example.invalid/configure-resource",
    )
    parser.add_argument(
        "--status-dir", type=Path, default=Path(".runtime/remote-affiliate-heartbeat")
    )
    parser.add_argument("--interval-seconds", type=float, default=20)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if not args.api_url.startswith("https://") or args.interval_seconds <= 0:
        parser.error("HTTPS and a positive interval are required")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
