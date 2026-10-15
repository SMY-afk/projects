"""Capture one verified HubStudio affiliate window and send its complete RAW batch."""

from __future__ import annotations

import argparse
import asyncio
import gzip
import os
import platform
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import httpx
from playwright.async_api import async_playwright

if os.name == "nt" and sys.version_info >= (3, 13):
    platform._wmi = None  # type: ignore[attr-defined]

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
from backend.app.services.tiktok_affiliate_analytics_capture import (
    TikTokAffiliateAnalyticsSynchronizer,
)
from backend.app.services.tiktok_affiliate_analytics_page_control import (
    RESOURCE_PAGE,
    matches_page,
)
from backend.app.services.tiktok_affiliate_analytics_pager import (
    TikTokAffiliateAnalyticsPager,
)
from backend.app.services.tiktok_affiliate_analytics_run_state import CaptureGuardConfig
from backend.app.services.tiktok_affiliate_intent_page import (
    prepare_intent_page,
)
from backend.app.services.tiktok_affiliate_scheduled_creator_page import close_owned_page
from erp_api.services.affiliate_capture_intent_repository import AffiliateCaptureIntent
from erp_api.services.remote_affiliate_capture import (
    RemoteAffiliateBatch,
    RemoteAffiliatePage,
)


async def capture(args: argparse.Namespace) -> RemoteAffiliateBatch:
    discovered = args.cdp_url or await discover_hubstudio_cdp_url(
        current_url=None, expected_platform_shop_id=args.platform_shop_id
    )
    cdp_url = normalize_loopback_cdp_url(discovered)
    if cdp_url is None or assert_erp_hubstudio_cdp_url(cdp_url) != cdp_url:
        raise RuntimeError("HubStudio CDP ownership is invalid")
    if not await probe_cdp_endpoint(cdp_url):
        raise RuntimeError("HubStudio CDP is unavailable")
    if await read_cdp_platform_shop_ids(cdp_url) != frozenset({args.platform_shop_id}):
        raise RuntimeError("HubStudio CDP shop identity does not match")
    zone = ZoneInfo(args.shop_timezone)
    start = datetime.combine(args.window_start, datetime.min.time(), zone)
    end = datetime.combine(args.window_end, datetime.min.time(), zone)
    intent = AffiliateCaptureIntent(
        run_id=uuid4(),
        job_id=f"remote-affiliate:{uuid4()}",
        tenant_id=UUID(int=0),
        shop_id=args.shop_id,
        resource=args.resource,
        resource_type=(
            "affiliate_creator" if args.resource == "creators" else "affiliate_video"
        ),
        platform_shop_id=args.platform_shop_id,
        shop_timezone=args.shop_timezone,
        currency=args.currency,
        window_start=start,
        window_end=end + timedelta(days=1),
    )
    pages: list[RemoteAffiliatePage] = []
    done = asyncio.Event()
    terminal: dict[str, object] = {}
    mutation_lock = asyncio.Lock()
    async with async_playwright() as playwright:
        browser = await connect_attached_hubstudio_browser(playwright, cdp_url)
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
        context = contexts[0]
        if args.resource == "videos" and not any(
            matches_page(page, RESOURCE_PAGE["videos"][0])
            and parse_qs(urlsplit(page.url).query).get("shop_id")
            == [args.platform_shop_id]
            for page in context.pages
        ):
            raise RuntimeError("Verified video page must already be open")
        pages_before = set(context.pages)
        try:
            prepared = await prepare_intent_page(contexts, intent)
        except Exception:
            for owned_page in set(context.pages) - pages_before:
                await close_owned_page(owned_page)
            raise

        async def persist(resource, payload, observation, response, number, next_number):
            if resource != args.resource or response.platform_shop_id != args.platform_shop_id:
                raise RuntimeError("Affiliate response shop/resource changed")
            if response.request_id is None:
                raise RuntimeError("Affiliate response request ID is absent")
            pages.append(
                RemoteAffiliatePage(
                    page_number=number,
                    next_page_number=next_number,
                    request_id=response.request_id,
                    observed_at=datetime.now(UTC),
                    payload=dict(payload),
                    observation=dict(observation),
                )
            )

        async def finalize(resource, snapshot):
            if resource == args.resource:
                terminal.update(snapshot)
                done.set()

        pager = TikTokAffiliateAnalyticsPager(
            mutation_lock,
            guard_config=CaptureGuardConfig(max_pages=200, max_run_seconds=1800),
            page_persister=persist,
            terminal_handler=finalize,
            page_requester=getattr(prepared.trigger, "request_page", None),
            page_number_provider=getattr(prepared.trigger, "current_page", None),
        )

        async def payload_handler(page, resource, payload, observation, response):
            if page is prepared.page and resource == args.resource:
                await pager.handle_payload(page, resource, payload, observation, response)

        async def failure_handler(page, resource, status, category):
            if page is prepared.page and resource == args.resource:
                await pager.handle_failure(page, resource, status, category)

        synchronizer = TikTokAffiliateAnalyticsSynchronizer(
            mutation_lock,
            payload_handler=payload_handler,
            failure_handler=failure_handler,
        )
        context.on("response", synchronizer.schedule_response)
        try:
            await prepared.trigger()
            await asyncio.wait_for(done.wait(), timeout=args.capture_timeout)
        finally:
            context.remove_listener("response", synchronizer.schedule_response)
            await pager.stop()
            await synchronizer.wait_for_pending()
            await prepared.cleanup()
            for owned_page in set(context.pages) - pages_before:
                await close_owned_page(owned_page)
    if terminal.get("status") != "complete" or not pages:
        raise RuntimeError(f"Affiliate capture did not complete: {terminal.get('status')}")
    if pages[-1].next_page_number is not None:
        raise RuntimeError("Affiliate terminal page was not confirmed")
    return RemoteAffiliateBatch(
        capture_id=uuid4(),
        shop_id=args.shop_id,
        environment_id=args.environment_id,
        platform_shop_id=args.platform_shop_id,
        resource=args.resource,
        window_start=args.window_start,
        window_end=args.window_end,
        pages=pages,
    )


async def run(args: argparse.Namespace) -> None:
    args.spool_dir.mkdir(parents=True, exist_ok=True)
    pending = sorted(args.spool_dir.glob("pending-*.json"))
    if len(pending) > 1 or (pending and args.capture):
        raise RuntimeError("Resolve the pending affiliate batch before another capture")
    if args.capture:
        batch = await capture(args)
        path = args.spool_dir / f"pending-{batch.capture_id}.json"
        path.write_text(batch.model_dump_json(), encoding="utf-8")
    elif pending:
        path = pending[0]
        batch = RemoteAffiliateBatch.model_validate_json(path.read_bytes())
    else:
        raise RuntimeError("No pending affiliate batch; use --capture")
    token = args.token_file.read_text(encoding="utf-8").strip()
    if len(token) < 32:
        raise RuntimeError("Affiliate token file is missing or too short")
    payload = batch.model_dump_json().encode("utf-8")
    compressed = gzip.compress(payload, compresslevel=6)
    if len(compressed) >= 1024 * 1024:
        raise RuntimeError("Compressed affiliate batch exceeds ERP proxy limit")
    async with httpx.AsyncClient(timeout=180, follow_redirects=False) as client:
        response = await client.post(
            args.api_url,
            content=compressed,
            headers={
                "content-type": "application/json",
                "content-encoding": "gzip",
                "x-erp-affiliate-capture-token": token,
            },
        )
    if response.status_code != 202 or response.json().get("status") != "stored":
        raise RuntimeError(f"ECS rejected affiliate batch: HTTP {response.status_code}")
    receipt = response.json()
    if not receipt.get("run_id"):
        raise RuntimeError("ECS did not return a durable affiliate run receipt")
    path.rename(path.with_name(path.name.replace("pending-", "stored-", 1)))
    print(
        f"AFFILIATE_BATCH_STORED shop={batch.shop_id} resource={batch.resource} "
        f"date={batch.window_end} pages={len(batch.pages)} run={receipt['run_id']} "
        f"duplicate={receipt.get('duplicate')}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shop-id", type=UUID, required=True)
    parser.add_argument("--environment-id", required=True)
    parser.add_argument("--platform-shop-id", required=True)
    parser.add_argument("--shop-timezone", required=True)
    parser.add_argument("--currency", required=True)
    parser.add_argument("--resource", choices=("creators", "videos"), required=True)
    parser.add_argument("--window-start", type=date.fromisoformat, required=True)
    parser.add_argument("--window-end", type=date.fromisoformat, required=True)
    parser.add_argument("--cdp-url")
    parser.add_argument("--capture", action="store_true")
    parser.add_argument("--capture-timeout", type=float, default=1800)
    parser.add_argument("--spool-dir", type=Path, required=True)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--api-url", default="https://example.invalid/configure-resource")
    args = parser.parse_args()
    if not args.api_url.startswith("https://"):
        parser.error("HTTPS is required")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
