"""Capture Creator details, reusing the approved shop's paid collection page."""

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from urllib.parse import quote, urlsplit

from playwright.async_api import async_playwright

from backend.app.services.local_refundable_page_guard import (
    is_local_paid_landing,
    restore_local_owned_redirect,
)
from backend.app.services.refundable_profile_cache import RefundableProfileCache
from backend.app.services.sample_persistent_target import persistent_sample_key
from backend.app.services.sample_raw_owned_page import open_owned_sample_page
from backend.app.services.tiktok_affiliate_analytics_page_control import (
    page_security_failure,
)
from backend.app.services.tiktok_sample_creator_details_collector import (
    creator_details_url,
)
from erp_api.services.affiliate_center_capture_policy import sanitize_capture_payload
from erp_api.services.refundable_identity_guard import quarantined_payload


@asynccontextmanager
async def _profile_page(endpoint, platform_id, host, reuse_page):
    if reuse_page is not None:
        yield reuse_page, reuse_page.url
        return
    async with (
        async_playwright() as playwright,
        open_owned_sample_page(
            playwright, endpoint, platform_id, host=host, purpose="refundable"
        ) as source,
    ):
        yield source


async def capture_refundable_profiles(
    endpoint, platform_id, items, *, host, reuse_page=None, profile_cache=None
):
    original_url = reuse_page.url if reuse_page is not None else None
    try:
        return await _capture_profiles(
            endpoint, platform_id, items, host=host,
            reuse_page=reuse_page, profile_cache=profile_cache,
        )
    finally:
        if (reuse_page is not None
                and urlsplit(reuse_page.url).path == "/affiliate/creator/detail"
                and not await page_security_failure(reuse_page)):
            await asyncio.wait_for(reuse_page.goto(
                original_url, wait_until="commit", timeout=15_000
            ), timeout=15)
        elif reuse_page is not None:
            await restore_local_owned_redirect(reuse_page, endpoint, platform_id, host, original_url)


async def _capture_profiles(
    endpoint, platform_id, items, *, host, reuse_page=None, profile_cache=None
):
    profiles = {}
    navigations = 0
    items = [item for item in items if not quarantined_payload(item)]
    if (
        profile_cache is None
        and reuse_page is not None
        and persistent_sample_key(platform_id, "refundable")
    ):
        profile_cache = RefundableProfileCache()
    selected = (
        profile_cache.select_due(
            platform_id, items, limit=1 if platform_id == "9622543325839925006" else 3
        )
        if isinstance(profile_cache, RefundableProfileCache) else None
    )
    for item in items:
        username = item["creator"]["username"]
        if username in profiles:
            continue
        responses = []
        tasks = set()
        expected_creator_id = str(item["creator"]["creator_open_id"])
        if profile_cache is not None:
            cached = profile_cache.load(platform_id, expected_creator_id, username)
            if cached is not None:
                profiles[username] = cached
                continue
            if selected is not None and expected_creator_id not in selected:
                profiles[username] = []
                continue
            if isinstance(profile_cache, RefundableProfileCache):
                profile_cache.mark_attempt(platform_id, expected_creator_id)
        navigations += 1
        if navigations > 1:
            await asyncio.sleep(2)

        async def read(
            response, responses=responses, expected_creator_id=expected_creator_id
        ):
            if (
                not urlsplit(response.url).path.endswith(
                    "/oec/affiliate/creator/marketplace/profile"
                )
                or response.request.method != "POST"
                or response.status != 200
            ):
                return
            body = sanitize_capture_payload(
                json.loads(response.request.post_data or "{}")
            )
            if (
                reuse_page is not None
                and str(body.get("creator_oec_id")) != expected_creator_id
            ):
                return
            kinds = body.get("profile_types")
            if (
                not isinstance(kinds, list)
                or len(kinds) != 1
                or kinds[0] not in range(1, 6)
            ):
                return
            payload = sanitize_capture_payload(await response.json())
            if payload.get("code", 0) != 0 or not body.get("creator_oec_id"):
                return
            responses.append(
                {
                    "request": body,
                    "payload": payload,
                    "observed_at": datetime.now(UTC).isoformat(),
                }
            )

        def schedule(response, tasks=tasks, read=read):
            task = asyncio.create_task(read(response))
            tasks.add(task)
            task.add_done_callback(tasks.discard)

        try:
            async with _profile_page(endpoint, platform_id, host, reuse_page) as (
                page,
                url,
            ):
                page.on("response", schedule)
                try:
                    if failure := await page_security_failure(page):
                        raise RuntimeError(failure[1])
                    detail_url = creator_details_url(url, platform_id, username)
                    detail_url += "&cid=" + quote(
                        item["creator"]["creator_open_id"], safe=""
                    )
                    await page.goto(
                        detail_url, wait_until="domcontentloaded", timeout=45_000
                    )
                    for _ in range(40):
                        if {
                            row["request"]["profile_types"][0] for row in responses
                        } == set(range(1, 6)):
                            break
                        await asyncio.sleep(0.25)
                    if failure := await page_security_failure(page):
                        raise RuntimeError(failure[1])
                finally:
                    page.remove_listener("response", schedule)
                    if tasks:
                        await asyncio.gather(*tuple(tasks), return_exceptions=True)
        except Exception as error:
            if reuse_page is not None:
                failure = await page_security_failure(reuse_page)
                if failure:
                    raise RuntimeError(failure[1]) from error
            print(
                f"REFUNDABLE_PROFILE_UNAVAILABLE error={type(error).__name__}",
                flush=True,
            )
        profiles[username] = responses
        if profile_cache is not None:
            profile_cache.save(platform_id, expected_creator_id, username, responses)
        print(f"REFUNDABLE_PROFILE_CAPTURED sources={len(responses)}", flush=True)
        if reuse_page is not None and is_local_paid_landing(reuse_page.url, platform_id, host):
            break
    if profile_cache is not None:
        for item in items:
            creator = item["creator"]
            profiles[creator["username"]] = (
                profile_cache.load(
                    platform_id, str(creator["creator_open_id"]), creator["username"]
                )
                or []
            )
    return profiles
