"""Full free-review RAW on one existing local target, isolated from other tabs."""

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
from playwright.async_api import async_playwright

from backend.app.services.hubstudio_attached_browser import (
    connect_attached_hubstudio_browser,
)
from backend.app.services.hubstudio_cdp import read_cdp_platform_shop_ids
from backend.app.services.hubstudio_raw_sample_capture import (
    capture_review_batch_from_page,
)
from backend.app.services.local_refundable_page_guard import is_local_paid_landing
from backend.app.services.sample_raw_batch_store import (
    SampleRawBatch,
    SampleRawBatchStore,
)
from backend.app.services.sample_raw_capture_retry import recover_fresh_completed
from backend.app.services.tiktok_affiliate_analytics_page_control import (
    page_security_failure,
)
from scripts.local_capture_guard import ROOT as GUARD_ROOT
from scripts.local_capture_guard import CaptureGuardError, browser_work
from scripts.local_paid_readiness import ensure_local_paid_ready
from scripts.local_sample_metadata_owned_cdp import existing_local_cdp
from scripts.local_sample_metadata_rules import LOCAL_SHOP, PLATFORM_SHOP, capture_scope
from scripts.ziniao_affiliate_export_source import resolve_ziniao_export_source

HOST = "affiliate-us.tiktok.com"
SAMPLE_PATH = "/affiliate/sample/sample-request"
SAMPLE_URL = f"https://{HOST}{SAMPLE_PATH}?shop_region=US&shop_id={PLATFORM_SHOP}"
API_PATH = "/api/v1/affiliate/sample/group/list"


def page_matches(url):
    split = urlsplit(url)
    return (split.scheme == "https" and split.hostname == HOST and split.path == SAMPLE_PATH
            and parse_qs(split.query).get("shop_id") == [PLATFORM_SHOP])


async def verify_page(page, endpoint):
    if failure := await page_security_failure(page):
        raise RuntimeError(failure[1])
    if not page_matches(page.url):
        raise RuntimeError("metadata_page_identity_changed")
    if await read_cdp_platform_shop_ids(endpoint) != frozenset({PLATFORM_SHOP}):
        raise RuntimeError("metadata_browser_identity_changed")


class GuardedResponse:
    def __init__(self, response, page, endpoint):
        self.response, self.page, self.endpoint = response, page, endpoint

    def __getattr__(self, name):
        return getattr(self.response, name)

    @property
    def status(self):
        if self.response.status in {401, 403}:
            raise CaptureGuardError("session_expired")
        return self.response.status

    async def json(self):
        await verify_page(self.page, self.endpoint)
        split = urlsplit(self.response.url)
        if (split.scheme != "https" or split.hostname != HOST or split.path != API_PATH
                or not page_matches(self.response.request.frame.url)):
            raise RuntimeError("metadata_response_identity_changed")
        payload = await self.response.json()
        request = json.loads(self.response.request.post_data or "{}")
        data = payload.get("data") if isinstance(payload, dict) else None
        for values in (parse_qs(split.query), request, payload, data):
            if not isinstance(values, dict):
                continue
            for key in ("shop_id", "oec_seller_id"):
                if key in values and values[key] not in (PLATFORM_SHOP, [PLATFORM_SHOP]):
                    raise RuntimeError("metadata_response_identity_changed")
        return payload


class GuardedPage:
    def __init__(self, page, endpoint):
        self.page, self.endpoint, self.callbacks = page, endpoint, {}

    def __getattr__(self, name):
        return getattr(self.page, name)

    def on(self, event, callback):
        if event == "response":
            wrapped = lambda response: callback(GuardedResponse(response, self.page, self.endpoint))
            self.callbacks[(event, callback)] = wrapped
            self.page.on(event, wrapped)
        else:
            self.page.on(event, callback)

    def remove_listener(self, event, callback):
        self.page.remove_listener(event, self.callbacks.pop((event, callback), callback))


def require_free_slot(*, root=GUARD_ROOT):
    path = root / "local.free-priority.json"
    try:
        row = json.loads(path.read_text(encoding="utf-8"))
        age = (datetime.now(UTC) - datetime.fromisoformat(row["last_success_at"])).total_seconds()
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise CaptureGuardError("free_priority_wait") from error
    if row.get("state") != "idle" or not 0 <= age <= 900:
        raise CaptureGuardError("free_priority_wait")
    # The browser_work shop lock excludes paid work for this free metadata
    # capture. Never fabricate/overwrite the official free success watermark.


async def capture(manifest, root, *, guard_root=GUARD_ROOT):
    root = Path(root)
    with browser_work("local", root=guard_root):
        require_free_slot(root=guard_root)
        endpoint, environment = await resolve_ziniao_export_source(PLATFORM_SHOP)
        await ensure_local_paid_ready(endpoint)
        async with httpx.AsyncClient(timeout=3) as client:
            before = (await client.get(f"{endpoint}/json/list")).json()
        store = SampleRawBatchStore(root / "raw", LOCAL_SHOP)
        await asyncio.to_thread(recover_fresh_completed, store)
        async with async_playwright() as playwright, existing_local_cdp(endpoint) as (proxy, target, registry):
            attached = await connect_attached_hubstudio_browser(playwright, proxy, timeout_seconds=15)
            pages = [page for context in attached.contexts for page in context.pages]
            if len(pages) != 1:
                raise RuntimeError("metadata_owned_target_ambiguous")
            page = pages[0]
            if not (page_matches(page.url) or is_local_paid_landing(page.url, PLATFORM_SHOP, HOST)):
                raise RuntimeError("metadata_existing_page_route_changed")
            captured = await capture_review_batch_from_page(
                GuardedPage(page, endpoint), PLATFORM_SHOP, store, timeout_seconds=60,
                initial_url=None if page_matches(page.url) else SAMPLE_URL,
            )
            await verify_page(page, endpoint)
        raw = store.load_pages(captured.batch)
        result = {
            "shop_id": LOCAL_SHOP, "platform_shop_id": PLATFORM_SHOP,
            "environment_id": environment,
            "observed_at": min(row.response_observed_at for row in raw).isoformat(),
            "page_count": captured.batch.page_count, "expected_total": captured.batch.expected_total,
            "captured_total": captured.batch.captured_total,
            "raw_batch_sequence": captured.batch.sequence,
            "pagination_complete": True, "terminal_confirmed": True,
            "tab": 10, "sort": "request_date", "request_id": raw[-1].request_id,
            "pages": [{"page": row.request_page, "cursor": row.request_cursor,
                       "request_id": row.request_id, "has_more": row.response_has_more} for row in raw],
            "applications": [app for parsed in captured.pages for app in parsed.applications],
        }
        try:
            capture_scope(manifest, result)
        except Exception:
            # Never replay a completed but candidate-mismatched window forever;
            # retain the evidence and recapture after normal five-minute backoff.
            store.supersede_completed(captured.batch, reason="metadata_scope_verification_failed")
            raise
        async with httpx.AsyncClient(timeout=3) as client:
            after = (await client.get(f"{endpoint}/json/list")).json()
        if ({row["id"] for row in before if row.get("type") == "page"}
                != {row["id"] for row in after if row.get("type") == "page"}
                or registry.resolve(after) != target):
            raise RuntimeError("metadata_page_inventory_changed")
        return result, str(captured.batch.path)


def finish_raw(root, row, *, superseded=False):
    """Acknowledge only our exact durable batch; preserve all RAW and history."""
    expected = Path(root).resolve() / "raw" / LOCAL_SHOP / f'batch-{row["capture"]["raw_batch_sequence"]:012d}'
    if Path(row["raw_batch_dir"]).resolve() != expected:
        raise RuntimeError("metadata_raw_batch_scope_invalid")
    manifest = json.loads((expected / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("status") in {"processed", "superseded"}:
        return
    batch = SampleRawBatch(manifest["sequence"], expected, manifest["page_count"],
                           manifest.get("expected_total"), manifest["captured_total"])
    store = SampleRawBatchStore(Path(root) / "raw", LOCAL_SHOP)
    if superseded:
        store.supersede_completed(batch, reason="metadata_capture_expired")
    else:
        store.acknowledge(batch)
