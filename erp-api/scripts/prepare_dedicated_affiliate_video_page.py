"""Create one approved source-video tab per shop and retain its exact target."""

import argparse
import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit
from uuid import uuid4

from playwright.async_api import async_playwright

from backend.app.services.hubstudio_attached_browser import (
    connect_attached_hubstudio_browser,
)
from backend.app.services.hubstudio_cdp import (
    discover_hubstudio_cdp_url,
    read_cdp_platform_shop_ids,
)
from backend.app.services.hubstudio_cdp_ownership import assert_erp_hubstudio_cdp_url
from backend.app.services.tiktok_affiliate_analytics_page_control import (
    page_security_failure,
)
from backend.app.services.tiktok_affiliate_intent_page import _resource_page_url
from scripts.affiliate_export_page import HOSTS, _existing_video_page, _same_video_shop
from scripts.local_capture_guard import CaptureGuardError, browser_work
from scripts.run_auto_affiliate_exports import ROOT, execute_window, fetch_plan
from scripts.run_remote_sample_capture_loop import SHOPS
from scripts.sample_capture_priority import run_secondary


def _save_registry(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f".{uuid4().hex}.tmp")
    with temporary.open("x", encoding="utf-8") as output:
        json.dump(rows, output, ensure_ascii=False, sort_keys=True)
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)


async def _target_id(context, page):
    session = await context.new_cdp_session(page)
    try:
        value = (await session.send("Target.getTargetInfo")).get("targetInfo", {}).get("targetId")
        if not isinstance(value, str) or not value:
            raise RuntimeError("Dedicated page creation outcome unknown")
        return value
    finally:
        await session.detach()


async def prepare_registered_video_page(context, platform_shop_id, label, path, binding):
    rows = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if not isinstance(rows, dict):
        raise TypeError("Dedicated page registry binding is invalid")
    previous = rows.get(label)
    if previous is not None:
        if (not isinstance(previous, dict)
                or any(previous.get(key) != value for key, value in binding.items())):
            raise RuntimeError("Dedicated page registry binding differs from current shop")
        if not previous.get("target_id"):
            raise RuntimeError("Dedicated page creation outcome unknown; audit before retry")
        page = await _existing_video_page(context, platform_shop_id, previous["target_id"])
        security = await page_security_failure(page)
        if security is not None:
            raise RuntimeError("Dedicated video page blocked: " + security[1])
        return previous["target_id"]
    record = {**binding, "state": "creating", "target_id": None,
              "created_at": datetime.now(UTC).isoformat()}
    rows[label] = record
    _save_registry(path, rows)  # Persist intent before creation; unknown outcomes never recreate.
    page = await context.new_page()
    record.update(target_id=await _target_id(context, page), state="created")
    _save_registry(path, rows)
    split = urlsplit(_resource_page_url([context], "videos", platform_shop_id))
    if split.hostname not in HOSTS:
        raise RuntimeError("Dedicated video host is not approved")
    params = parse_qs(split.query)
    params["shop_id"] = [platform_shop_id]
    url = urlunsplit((split.scheme, split.netloc, split.path, urlencode(params, doseq=True), ""))
    await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
    if not _same_video_shop(page.url, platform_shop_id):
        raise RuntimeError("Dedicated video page changed shop identity")
    security = await page_security_failure(page)
    if security is not None:
        raise RuntimeError("Dedicated video page blocked: " + security[1])
    marker = "ERP_SOURCE_VIDEO_" + label
    await page.evaluate("marker => { window.name = marker; document.title = marker; }", marker)
    record["state"] = "ready"
    _save_registry(path, rows)
    return record["target_id"]


async def run(args):
    plan = await asyncio.to_thread(fetch_plan)
    erp_shop, environment, platform_shop = SHOPS[args.shop_label]
    shops = [row for row in plan["shops"] if row["shop_id"] == erp_shop]
    if len(shops) != 1:
        raise CaptureGuardError("shop_identity_missing")
    shop = shops[0]
    if not any(window["resource"] == "videos" for window in shop["missing"]):
        print(f"DEDICATED_VIDEO_SKIPPED shop={args.shop_label} reason=no_missing_video")
        return
    if not shop["health_ready"] or not shop["sample_released"]:
        raise CaptureGuardError("free_priority_wait")
    window = next(item for item in shop["missing"] if item["resource"] == "videos")

    async def prepare():
        endpoint = await discover_hubstudio_cdp_url(
            current_url=None, expected_platform_shop_id=platform_shop)
        if endpoint is None:
            raise CaptureGuardError("verified_shop_browser_unavailable")
        assert_erp_hubstudio_cdp_url(endpoint)
        if await read_cdp_platform_shop_ids(endpoint) != frozenset({platform_shop}):
            raise CaptureGuardError("shop_identity_mismatch")
        async with async_playwright() as playwright:
            browser = await connect_attached_hubstudio_browser(playwright, endpoint)
            contexts = [context for context in browser.contexts if any(
                parse_qs(urlsplit(page.url).query).get("shop_id") == [platform_shop]
                for page in context.pages)]
            if len(contexts) != 1:
                raise CaptureGuardError("shop_context_missing")
            binding = {"shop_id": erp_shop, "environment_id": environment, "cdp_url": endpoint}
            target = await prepare_registered_video_page(
                contexts[0], platform_shop, args.shop_label, args.registry, binding)
            print(f"DEDICATED_VIDEO_READY shop={args.shop_label} target={target}", flush=True)
        if args.recover_missing:
            args.approved_page_target_id = target
            args.sample_status_dir = ROOT / ".runtime/remote-sample-captures"
            args.spool_root = ROOT / ".runtime/affiliate-auto-export"
            args.capture_timeout = 480
            result = await execute_window(args, shop, window, args.shop_label)
            print(f"DEDICATED_VIDEO_RECOVERY shop={args.shop_label} state={result}", flush=True)
            if result == "stored":
                refreshed = await asyncio.to_thread(fetch_plan)
                current = next(row for row in refreshed["shops"] if row["shop_id"] == erp_shop)
                if window in current["missing"]:
                    raise RuntimeError("Stored video window remains missing after readback")
    with browser_work(args.shop_label):
        await run_secondary(args.shop_label, prepare)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shop-label", choices=("cross-border-3", "cross-border-4", "cross-border-12"), required=True)
    parser.add_argument("--registry", type=Path,
                        default=ROOT / ".runtime/affiliate-auto-export/video-page-targets.json")
    parser.add_argument("--recover-missing", action="store_true")
    parser.add_argument("--token-file", type=Path)
    args = parser.parse_args()
    if args.recover_missing and args.token_file is None:
        parser.error("--recover-missing requires --token-file")
    try:
        asyncio.run(run(args))
    except Exception as error:  # noqa: BLE001 - Report only safe error type/category at the CLI boundary.
        reason = getattr(error, "code", type(error).__name__)
        print(f"DEDICATED_VIDEO_DEFERRED shop={args.shop_label} reason={reason}", flush=True)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
