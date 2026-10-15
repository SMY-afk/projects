"""Fresh exact-shop evidence for the local collector's restored paid target."""

import asyncio
import json
from collections.abc import Mapping
from urllib.parse import parse_qs, urlsplit

import httpx

from backend.app.services.hubstudio_cdp import read_cdp_platform_shop_ids
from backend.app.services.sample_persistent_target import PersistentSampleTarget
from backend.app.services.tiktok_affiliate_analytics_page_control import (
    page_security_failure,
)
from erp_api.services.refundable_sample_parser import REFUNDABLE_PATH

LOCAL_SHOP = "9136806951995371293"
LOCAL_HOST = "affiliate-us.tiktok.com"
SAMPLE_PATH = "/affiliate/sample/sample-request"
OWNED_PAGE_FAILURE_CODES = frozenset({
    "owned_page_target_changed", "owned_page_shop_changed",
    "owned_page_registry_invalid", "approved_sample_browser_changed",
    "approved_sample_page_missing", "local_paid_page_identity_changed",
    "local_paid_browser_identity_changed", "local_paid_response_identity_changed",
})


def _local_scope(platform_id, host):
    return platform_id == LOCAL_SHOP and host == LOCAL_HOST


def is_local_paid_landing(url, platform_id, host):
    split = urlsplit(url)
    return (
        _local_scope(platform_id, host)
        and split.scheme == "https"
        and split.hostname == "seller-us.tiktok.com"
        and split.path == "/affiliate/landing"
        and parse_qs(split.query).get("shop_id", [LOCAL_SHOP]) == [LOCAL_SHOP]
        and parse_qs(split.query).get("oec_seller_id", [LOCAL_SHOP]) == [LOCAL_SHOP]
    )


def _expected_page(url):
    split = urlsplit(url)
    return (
        split.scheme == "https"
        and split.hostname == LOCAL_HOST
        and split.path == SAMPLE_PATH
        and parse_qs(split.query).get("shop_id") == [LOCAL_SHOP]
    )


async def verify_local_paid_page(page, endpoint, platform_id, host):
    if not _local_scope(platform_id, host):
        return
    if failure := await page_security_failure(page):
        raise RuntimeError(failure[1])
    if not _expected_page(page.url):
        raise RuntimeError("local_paid_page_identity_changed")
    if await read_cdp_platform_shop_ids(endpoint) != frozenset({LOCAL_SHOP}):
        raise RuntimeError("local_paid_browser_identity_changed")


async def verify_local_paid_response(page, response, request, payload, endpoint, platform_id, host):
    if not _local_scope(platform_id, host):
        return
    await verify_local_paid_page(page, endpoint, platform_id, host)
    split = urlsplit(response.url)
    if (split.scheme != "https" or split.hostname != LOCAL_HOST
            or split.path != REFUNDABLE_PATH
            or not _expected_page(response.request.frame.url)):
        raise RuntimeError("local_paid_response_identity_changed")
    data = payload.get("data") if isinstance(payload, Mapping) else None
    for value in (parse_qs(split.query), request, payload, data):
        if not isinstance(value, Mapping):
            continue
        for key in ("shop_id", "oec_seller_id"):
            if key in value and value[key] not in (LOCAL_SHOP, [LOCAL_SHOP]):
                raise RuntimeError("local_paid_response_identity_changed")


async def restore_local_owned_redirect(page, endpoint, platform_id, host, original_url):
    if not is_local_paid_landing(page.url, platform_id, host):
        return False
    if not _expected_page(original_url):
        raise RuntimeError("local_paid_page_identity_changed")
    if failure := await page_security_failure(page):
        raise RuntimeError(failure[1])
    async with httpx.AsyncClient(timeout=3) as client:
        version = (await client.get(f"{endpoint}/json/version")).json()
        targets = (await client.get(f"{endpoint}/json/list")).json()
    registry = PersistentSampleTarget((LOCAL_SHOP, "refundable"), version["webSocketDebuggerUrl"])
    if json.loads(registry.path.read_text())["ownership"] != "collector_created":
        raise RuntimeError("owned_page_target_changed")
    target_id = registry.resolve(targets)
    session = await page.context.new_cdp_session(page)
    try:
        info = await session.send("Target.getTargetInfo")
        current = info["targetInfo"]
        if (target_id is None or current["targetId"] != target_id
                or not is_local_paid_landing(current.get("url", ""), platform_id, host)):
            raise RuntimeError("owned_page_target_changed")
    finally:
        await session.detach()
    await asyncio.wait_for(page.goto(original_url, wait_until="commit", timeout=15_000), 15)
    await verify_local_paid_page(page, endpoint, platform_id, host)
    return True
