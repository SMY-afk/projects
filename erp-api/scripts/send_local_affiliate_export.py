"""Download one original TikTok affiliate XLSX and send it to the ECS API."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import platform
import sys
from dataclasses import asdict
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4

import httpx
from playwright.async_api import async_playwright

if os.name == "nt" and sys.version_info >= (3, 13):
    platform._wmi = None  # type: ignore[attr-defined]

from app.parsers.affiliate_video_export_parser import (
    AffiliateVideoExportParseError,
    parse_affiliate_video_export,
)
from backend.app.services.hubstudio_attached_browser import (
    connect_attached_hubstudio_browser,
)
from backend.app.services.hubstudio_cdp import (
    discover_hubstudio_cdp_url,
    normalize_loopback_cdp_url,
    probe_cdp_endpoint,
    read_cdp_platform_shop_ids,
)
from backend.app.services.hubstudio_cdp_ownership import assert_erp_hubstudio_cdp_url
from backend.app.services.tiktok_affiliate_video_export_download import (
    delete_download as delete_video_download,
)
from backend.app.services.tiktok_affiliate_video_export_download import (
    download_video_export,
)
from erp_api.services.affiliate_center_contract import (
    AffiliateCenterQuery,
    AffiliateCenterResource,
)
from erp_api.services.remote_affiliate_export import (
    RemoteAffiliateExportManifest,
    map_validated_export,
)
from scripts.affiliate_export_creator_capture import capture_creator_export
from scripts.affiliate_export_page import prepare_export_page as _prepare_owned_page
from scripts.affiliate_export_progress import mark_capture_phase
from scripts.affiliate_export_quarantine import quarantine_workbook
from scripts.ziniao_affiliate_export_source import (
    resolve_ziniao_export_source,
    verified_ziniao_download_dir,
)


def _query(args: argparse.Namespace) -> AffiliateCenterQuery:
    return AffiliateCenterQuery(
        resource=AffiliateCenterResource(args.resource),
        shop_id=args.shop_id,
        window_start=args.window_start,
        window_end=args.window_end,
        shop_timezone=args.shop_timezone,
        currency=args.currency,
        filters={},
    )


async def capture(args: argparse.Namespace):
    local_download_dir = None
    if args.browser_provider == "ziniao":
        cdp_url, args.environment_id = await resolve_ziniao_export_source(
            args.platform_shop_id
        )
        local_download_dir = await verified_ziniao_download_dir(cdp_url)
        if args.cdp_url and args.cdp_url != cdp_url:
            raise RuntimeError("Ziniao CDP URL differs from the running browser")
        discovered = cdp_url
    else:
        discovered = args.cdp_url or await discover_hubstudio_cdp_url(
            current_url=None, expected_platform_shop_id=args.platform_shop_id
        )
    cdp_url = normalize_loopback_cdp_url(discovered)
    if cdp_url is None or (
        args.browser_provider == "hubstudio"
        and assert_erp_hubstudio_cdp_url(cdp_url) != cdp_url
    ):
        raise RuntimeError("Affiliate CDP ownership is invalid")
    if not await probe_cdp_endpoint(cdp_url):
        raise RuntimeError("HubStudio CDP is unavailable")
    if await read_cdp_platform_shop_ids(cdp_url) != frozenset({args.platform_shop_id}):
        raise RuntimeError("HubStudio CDP shop identity does not match")
    query = _query(args)
    async with async_playwright() as playwright:
        browser = await connect_attached_hubstudio_browser(playwright, cdp_url)
        mark_capture_phase(args, "browser_connected")
        contexts = [
            context
            for context in browser.contexts
            if any(
                parse_qs(urlsplit(page.url).query).get("shop_id")
                == [args.platform_shop_id]
                for page in context.pages
            )
        ]
        if len(contexts) != 1:
            raise RuntimeError("Expected shop context is missing or ambiguous")
        prepared = await _prepare_owned_page(
            contexts[0], query, args.platform_shop_id,
            approved_page_target_id=getattr(args, "approved_page_target_id", None),
        )
        mark_capture_phase(args, "date_range_prepared")
        try:
            if args.resource == "creators":
                content, request_id, audit = await capture_creator_export(
                    prepared.page, prepared.trigger, args.currency, args.spool_dir,
                    allow_missing=args.exclude_missing_accounts,
                    local_download_dir=local_download_dir,
                    on_progress=lambda phase: mark_capture_phase(args, phase),
                )
                mark_capture_phase(args, "workbook_downloaded")
                source_total = audit.eligible_total
            else:
                audit = None
                content, task_id, download, request_id = await download_video_export(
                    prepared.page, query
                )
                try:
                    try:
                        rows = parse_affiliate_video_export(
                            content, args.currency, args.shop_timezone
                        )
                    except AffiliateVideoExportParseError:
                        quarantine_workbook(args.spool_dir, content)
                        raise
                    source_total = len(rows)
                    request_id = request_id or f"export:{hashlib.sha256(task_id.encode()).hexdigest()[:32]}"
                finally:
                    await delete_video_download(download)
        finally:
            await prepared.cleanup()
    manifest = RemoteAffiliateExportManifest(
        capture_id=uuid4(),
        shop_id=args.shop_id,
        platform_shop_id=args.platform_shop_id,
        environment_id=args.environment_id,
        resource=args.resource,
        window_start=args.window_start,
        window_end=args.window_end,
        observed_at=datetime.now(UTC),
        request_id=request_id,
        source_total=source_total,
        file_sha256=hashlib.sha256(content).hexdigest(),
    )
    map_validated_export(manifest, content, query)
    return manifest, content, audit


async def run(args: argparse.Namespace) -> None:
    args.spool_dir.mkdir(parents=True, exist_ok=True)
    pending = sorted(args.spool_dir.glob("pending-*"))
    if len(pending) > 1 or (pending and (args.capture or args.verify_capture_id)):
        raise RuntimeError("Resolve the pending XLSX before another capture")
    if args.verify_capture_id:
        folder = args.spool_dir / f"stored-{args.verify_capture_id}"
        if not folder.is_dir():
            raise RuntimeError("Stored XLSX capture is unavailable")
        manifest = RemoteAffiliateExportManifest.model_validate_json(
            (folder / "manifest.json").read_bytes()
        )
        content = (folder / "workbook.xlsx").read_bytes()
        map_validated_export(manifest, content, _query(args))
    elif args.capture:
        manifest, content, audit = await capture(args)
        folder = args.spool_dir / f"pending-{manifest.capture_id}"
        folder.mkdir(exist_ok=False)
        (folder / "workbook.xlsx").write_bytes(content)
        (folder / "manifest.json").write_text(
            manifest.model_dump_json(), encoding="utf-8"
        )
        if audit is not None:
            (folder / "creator-exclusion-audit.json").write_text(
                json.dumps(asdict(audit), sort_keys=True), encoding="utf-8"
            )
    elif pending:
        folder = pending[0]
        manifest = RemoteAffiliateExportManifest.model_validate_json(
            (folder / "manifest.json").read_bytes()
        )
        content = (folder / "workbook.xlsx").read_bytes()
        map_validated_export(manifest, content, _query(args))
    else:
        raise RuntimeError("No pending XLSX; use --capture")
    token = args.token_file.read_text(encoding="utf-8").strip()
    if len(token) < 32:
        raise RuntimeError("Affiliate token file is missing or too short")
    if len(content) > 25 * 1024 * 1024:
        raise RuntimeError("XLSX exceeds ERP ingress limit; original file stays pending")
    async with httpx.AsyncClient(timeout=180, follow_redirects=False) as client:
        response = await client.post(
            args.api_url,
            content=content,
            headers={
                "content-type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "x-erp-affiliate-capture-token": token,
                "x-erp-export-manifest": manifest.model_dump_json(),
            },
        )
    if response.status_code != 202 or response.json().get("status") != "stored":
        raise RuntimeError(f"ECS rejected XLSX: HTTP {response.status_code}")
    receipt = response.json()
    if not receipt.get("run_id"):
        raise RuntimeError("ECS did not return a durable export run receipt")
    if args.verify_capture_id:
        if receipt.get("duplicate") is not True:
            raise RuntimeError("ECS did not recognize the export replay")
    else:
        folder.rename(folder.with_name(folder.name.replace("pending-", "stored-", 1)))
    print(
        f"AFFILIATE_EXPORT_STORED shop={manifest.shop_id} resource={manifest.resource} "
        f"date={manifest.window_end} rows={manifest.source_total} "
        f"run={receipt['run_id']} duplicate={receipt.get('duplicate')}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shop-id", type=UUID, required=True)
    parser.add_argument("--environment-id")
    parser.add_argument(
        "--browser-provider", choices=("hubstudio", "ziniao"), default="hubstudio"
    )
    parser.add_argument("--platform-shop-id", required=True)
    parser.add_argument("--shop-timezone", required=True)
    parser.add_argument("--currency", required=True)
    parser.add_argument("--resource", choices=("creators", "videos"), required=True)
    parser.add_argument("--window-start", type=date.fromisoformat, required=True)
    parser.add_argument("--window-end", type=date.fromisoformat, required=True)
    parser.add_argument("--cdp-url")
    parser.add_argument("--approved-page-target-id")
    parser.add_argument("--capture", action="store_true")
    parser.add_argument("--exclude-missing-accounts", action="store_true")
    parser.add_argument("--verify-capture-id", type=UUID)
    parser.add_argument("--spool-dir", type=Path, required=True)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--api-url", default="https://example.invalid/configure-resource")
    args = parser.parse_args()
    if not args.api_url.startswith("https://"):
        parser.error("HTTPS is required")
    if args.browser_provider == "hubstudio" and not args.environment_id:
        parser.error("--environment-id is required for HubStudio")
    if args.exclude_missing_accounts and args.resource != "creators":
        parser.error("--exclude-missing-accounts is only valid for creators")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
