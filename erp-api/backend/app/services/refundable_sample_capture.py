"""Durable, isolated refundable status capture; never touch the free collector tab."""

import asyncio
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from playwright.async_api import async_playwright

from backend.app.services.local_refundable_page_guard import (
    verify_local_paid_page,
    verify_local_paid_response,
)
from backend.app.services.refundable_creator_profile_capture import (
    capture_refundable_profiles,
)
from backend.app.services.refundable_page_controls import (
    reset_selected_status,
    select_paid_panel,
)
from backend.app.services.sample_persistent_target import persistent_sample_key
from backend.app.services.sample_raw_batch_store import SampleRawBatchStore
from backend.app.services.sample_raw_capture_retry import recover_fresh_completed
from backend.app.services.sample_raw_owned_page import open_owned_sample_page
from backend.app.services.sample_request_page_controls import (
    next_sample_page,
    select_free_sample_tab,
)
from erp_api.services.refundable_sample_parser import (
    REFUNDABLE_PATH,
    parse_refundable_sample_page,
    validate_refundable_request,
)

TAB_LABELS = {
    1: r"^(?:Ready to Ship|待发货)",
    2: r"^(?:Shipped|已发货)",
    3: r"^(?:In[- ]progress|处理中)",
    4: r"^(?:Refunded|已退款|已返款)",
    5: r"^(?:Not refunded|未退款|未返款)",
    6: r"^(?:Cancel(?:l)?ed|已取消)",
}


async def capture_refundable_status(
    cdp_url,
    platform_shop_id,
    store,
    tab_type,
    *,
    timeout=60,
    host="affiliate.tiktokshopglobalselling.com",
):
    pending = (
        await asyncio.to_thread(recover_fresh_completed, store)
        if persistent_sample_key(platform_shop_id, "refundable")
        else store.recover_completed()
    )
    if pending is not None:
        return pending
    async with (
        async_playwright() as playwright,
        open_owned_sample_page(
            playwright, cdp_url, platform_shop_id, host=host, purpose="refundable"
        ) as (page, url),
    ):
        await _prepare_paid_page(page, url)
        await verify_local_paid_page(page, cdp_url, platform_shop_id, host)
        initial_response = await select_paid_panel(page, _paid_response)
        # TikTok keeps both lists mounted; aria-controls references no real panel.
        # The observed paid status header's grandparent owns only its paid pager.
        header = page.locator('div[class*="sample-status-tab__StyledTabs-"]').filter(visible=True)
        await header.wait_for(state="visible", timeout=30_000)
        if await header.count() != 1:
            raise RuntimeError("Refundable status container is missing or ambiguous")
        paid_panel = header.locator("xpath=../..")
        return await _capture_tab(
            page, store, tab_type, timeout, cdp_url, platform_shop_id, host,
            scope=paid_panel, initial_response=initial_response,
        )


async def _prepare_paid_page(page, url):
    if page.url != url:
        await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    # Clicking an already selected paid tab sends no request. Reset only this
    # approved collection page, without reloading or touching another target.
    await select_free_sample_tab(page)


def _paid_response(response):
    return (
        urlsplit(response.url).path == REFUNDABLE_PATH
        and response.request.method == "POST"
    )


async def _capture_tab(page, store, tab_type, timeout, endpoint, platform_id, host, *, scope=None, initial_response=None):
    await asyncio.to_thread(store.abandon_capturing, "capture_restarted")
    sequence = await asyncio.to_thread(store.start_batch)
    ids = set()
    total = None
    response_ids = set()
    staged = []
    scope = scope if scope is not None else page
    status_tab = scope.get_by_role(
        "tab", name=re.compile(TAB_LABELS[tab_type], re.IGNORECASE)
    )
    status_tab = status_tab.filter(visible=True)
    await status_tab.wait_for(state="visible", timeout=30_000)
    if await status_tab.count() != 1:
        raise RuntimeError("Refundable status tab is missing or ambiguous")

    def matches(response):
        if not _paid_response(response):
            return False
        try:
            request = validate_refundable_request(
                json.loads(response.request.post_data or "{}")
            )
        except (ValueError, UnicodeDecodeError):
            return False
        return request["tab_type"] == tab_type

    for number in range(1, 501):
        reuse_initial = (
            number == 1 and initial_response is not None and matches(initial_response)
            and json.loads(initial_response.request.post_data).get("cur_page") == 1
            and await status_tab.get_attribute("aria-selected") == "true"
        )
        if reuse_initial:
            response = initial_response
        else:
            if number == 1:
                await reset_selected_status(scope, status_tab, tab_type)
            async with page.expect_response(matches, timeout=timeout * 1000) as pending:
                if number == 1:
                    await status_tab.click(timeout=30_000)
                elif not await next_sample_page(scope):
                    raise RuntimeError("Refundable next page is missing")
            response = await pending.value
        observed_at = datetime.now(UTC)
        if response.status != 200:
            raise RuntimeError("Refundable source HTTP failure")
        request = validate_refundable_request(json.loads(response.request.post_data))
        if request["cur_page"] != number:
            raise RuntimeError("Refundable source page sequence changed")
        payload = await response.json()
        await verify_local_paid_response(
            page, response, request, payload, endpoint, platform_id, host
        )
        header_names = ("x-tt-logid", "x-tt-trace-id", "x-request-id")
        request_id = None
        for key in header_names:
            request_id = await response.header_value(key)
            if request_id:
                break
        if not request_id or request_id in response_ids:
            raise RuntimeError(
                "Refundable source request identity is missing or repeated"
            )
        response_ids.add(request_id)
        wrapper = {"refundable_response": payload, "refundable_request": request}
        data = payload.get("data") if isinstance(payload, dict) else None
        raw_total = data.get("total_count") if isinstance(data, dict) else None
        if type(raw_total) is not int or raw_total < 0:
            raw_total = None
        # Keep the received RAW page even when identity normalization fails.
        # Only the fully validated path below can ever complete/publish a batch.
        await asyncio.to_thread(
            store.persist_page, sequence, number, wrapper,
            request_id=request_id, request_page=number,
            request_cursor=f"{tab_type}:{number}",
            response_has_more=None if raw_total is None else number * request["page_size"] < raw_total,
            response_total_count=raw_total, response_observed_at=observed_at,
        )
        parsed = parse_refundable_sample_page(
            payload, request=request, request_id=request_id, observed_at=observed_at
        )
        if total is not None and total != parsed.total_count:
            raise RuntimeError("Refundable source total changed")
        total = parsed.total_count
        page_ids = {item["id"] for item in parsed.applications}
        if len(page_ids) != len(parsed.applications) or ids & page_ids:
            raise RuntimeError("Refundable source application identity is duplicated")
        ids.update(page_ids)
        staged.append((number, wrapper, request_id, observed_at, parsed))
        if parsed.next_page_token is None:
            if len(ids) != total:
                raise RuntimeError(
                    "Refundable captured total differs from expected total"
                )
            if tab_type in (1, 2, 3):
                profiles = await capture_refundable_profiles(
                    endpoint,
                    platform_id,
                    [item for _, _, _, _, page in staged for item in page.applications],
                    host=host,
                    reuse_page=page
                    if persistent_sample_key(platform_id, "refundable")
                    else None,
                )
                for page_number, wrapper, page_id, page_time, page_value in staged:
                    wrapper["refundable_profiles"] = profiles
                    await asyncio.to_thread(
                        store.persist_page,
                        sequence,
                        page_number,
                        wrapper,
                        request_id=page_id,
                        request_page=page_number,
                        request_cursor=f"{tab_type}:{page_number}",
                        response_has_more=page_value.next_page_token is not None,
                        response_total_count=total,
                        response_observed_at=page_time,
                    )
            return await asyncio.to_thread(
                store.complete_batch,
                sequence,
                number,
                expected_total=total,
                captured_total=len(ids),
                terminal_confirmed=True,
            )
    raise RuntimeError("Refundable pagination exceeded the safety limit")


def refundable_store(root: Path, shop_id, tab_type):
    if tab_type not in TAB_LABELS:
        raise ValueError("Refundable source tab is invalid")
    return SampleRawBatchStore(root, f"{shop_id}-refundable-{tab_type}")
