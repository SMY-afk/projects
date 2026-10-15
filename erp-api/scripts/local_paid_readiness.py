"""Verify the real local paid target without adopting a stalled sibling page."""

import asyncio
import json
from urllib.parse import urlsplit

import httpx

from backend.app.services.hubstudio_cdp import read_cdp_platform_shop_ids
from backend.app.services.local_browser_security import HOSTS, _page_state
from backend.app.services.local_refundable_page_guard import LOCAL_SHOP
from backend.app.services.sample_persistent_target import PersistentSampleTarget
from scripts.local_capture_guard import CaptureGuardError, pause_shop


async def ensure_local_paid_ready(endpoint):
    if await read_cdp_platform_shop_ids(endpoint) != frozenset({LOCAL_SHOP}):
        raise RuntimeError("local_paid_browser_identity_changed")
    async with httpx.AsyncClient(timeout=3) as client:
        version_response = await client.get(f"{endpoint}/json/version")
        targets_response = await client.get(f"{endpoint}/json/list")
        version_response.raise_for_status()
        targets_response.raise_for_status()
        version, targets = version_response.json(), targets_response.json()
    registry = PersistentSampleTarget((LOCAL_SHOP, "refundable"), version["webSocketDebuggerUrl"])
    if json.loads(registry.path.read_text())["ownership"] != "collector_created":
        raise RuntimeError("owned_page_target_changed")
    target_id = registry.resolve(targets)
    if not target_id:
        raise RuntimeError("owned_page_target_changed")
    business = [row for row in targets if row.get("type") == "page"
                and urlsplit(row.get("url", "")).hostname in HOSTS | {"seller-us.tiktok.com"}]
    results = await asyncio.gather(*(_page_state(row) for row in business), return_exceptions=True)
    for state in ("captcha", "session_expired"):
        if state in results:
            pause_shop("local", state)
            raise CaptureGuardError(state)
    actual = next((state for row, state in zip(business, results, strict=True)
                   if row["id"] == target_id), None)
    if actual != "online":
        raise CaptureGuardError("connecting")
