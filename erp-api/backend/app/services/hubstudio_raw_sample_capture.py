"""Durable RAW capture for every request-date-sorted review page."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlsplit

from playwright.async_api import Page, Response, async_playwright

from backend.app.services.hubstudio_sample_network_listener import (
    DEFAULT_SAMPLE_RESPONSE_HOSTS,
    _is_review_request_date,
)
from backend.app.services.hubstudio_sample_watch import _sample_page_matches
from backend.app.services.sample_queue_backpressure import put_with_backpressure
from backend.app.services.sample_raw_batch_store import (
    SampleRawBatch,
    SampleRawBatchStore,
)
from backend.app.services.sample_raw_capture_metadata import (
    SampleRawRequestMarker,
    parse_capture_request_marker,
    read_response_metadata,
    validate_captured_pages,
)
from backend.app.services.sample_raw_owned_page import open_owned_sample_page
from backend.app.services.sample_request_page_controls import next_sample_page
from backend.app.services.sample_review_page_refresh import (
    _load_first_page,
    prepare_reused_review,
    trigger_review_refresh,
)
from erp_api.services.hubstudio_sample_response_parser import (
    parse_hubstudio_sample_response,
)
from erp_api.services.tiktok_sample_application_payload import (
    TikTokSampleApplicationPage,
)

SAMPLE_API_PATH = "/api/v1/affiliate/sample/group/list"
MAX_REVIEW_PAGES = 500


@dataclass(frozen=True)
class SampleRawCaptureBatch:
    batch: SampleRawBatch
    pages: tuple[TikTokSampleApplicationPage, ...]
    recovered: bool


@dataclass(frozen=True)
class _CapturedPage:
    sequence: int
    page: TikTokSampleApplicationPage


def is_review_request_date(url: str, method: str, body: str | None) -> bool:
    split = urlsplit(url)
    return bool(
        split.hostname in DEFAULT_SAMPLE_RESPONSE_HOSTS
        and split.path == SAMPLE_API_PATH
        and method == "POST"
        and _is_review_request_date(body)
    )


async def capture_review_batch(
    cdp_url: str,
    platform_shop_id: str,
    store: SampleRawBatchStore,
    *,
    timeout_seconds: float = 45,
) -> SampleRawCaptureBatch:
    """Capture in an owned tab without closing the externally owned browser."""
    split = urlsplit(cdp_url)
    if (
        timeout_seconds <= 0
        or not platform_shop_id.strip()
        or split.scheme != "http"
        or split.hostname not in {"127.0.0.1", "localhost"}
    ):
        raise ValueError("Raw sample capture target is invalid")
    recovered = _recover(store)
    if recovered is not None:
        return recovered
    async with (
        async_playwright() as playwright,
        open_owned_sample_page(playwright, cdp_url, platform_shop_id) as (
            owned_page,
            owned_url,
        ),
    ):
        return await capture_review_batch_from_page(
            owned_page,
            platform_shop_id,
            store,
            timeout_seconds=timeout_seconds,
            initial_url=None
            if _sample_page_matches(owned_page.url, platform_shop_id)
            else owned_url,
        )


async def capture_review_batch_from_page(
    page: Page,
    platform_shop_id: str,
    store: SampleRawBatchStore,
    *,
    timeout_seconds: float = 45,
    initial_url: str | None = None,
) -> SampleRawCaptureBatch:
    """Capture first, persist RAW pages, then return them for business parsing."""
    recovered = _recover(store)
    if recovered is not None:
        return recovered
    reused = await prepare_reused_review(page, platform_shop_id, initial_url)
    await asyncio.to_thread(store.abandon_capturing, "capture_restarted")
    batch_sequence = await asyncio.to_thread(store.start_batch)
    queue: asyncio.Queue[_CapturedPage | Exception] = asyncio.Queue(maxsize=16)
    tasks: set[asyncio.Task[None]] = set()
    next_sequence = 0
    accepting = True
    started_requests = {}

    def started(request):
        try:
            if is_review_request_date(request.url, request.method, request.post_data):
                started_requests[id(request)] = request
        except UnicodeDecodeError:
            return

    def schedule(response: Response) -> None:
        nonlocal next_sequence
        if not accepting:
            return
        if reused and id(response.request) not in started_requests:
            return
        try:
            post_data = response.request.post_data
        except UnicodeDecodeError:
            return
        if not is_review_request_date(response.url, response.request.method, post_data):
            return
        next_sequence += 1
        marker = parse_capture_request_marker(post_data, next_sequence)
        observed_at = datetime.now(UTC)
        task = asyncio.create_task(
            _read_response(
                response,
                page,
                platform_shop_id,
                store,
                batch_sequence,
                next_sequence,
                marker,
                queue,
                observed_at,
            )
        )
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    if reused:
        page.on("request", started)
    page.on("response", schedule)
    try:
        if reused:
            await trigger_review_refresh(page)
        else:
            await _load_first_page(page, platform_shop_id, initial_url)
        pages: list[TikTokSampleApplicationPage] = []
        buffered: dict[int, TikTokSampleApplicationPage] = {}
        for page_sequence in range(1, MAX_REVIEW_PAGES + 1):
            captured_page = await _receive(
                queue, buffered, page_sequence, timeout_seconds
            )
            pages.append(captured_page)
            if captured_page.next_page_token is None or not await next_sample_page(
                page
            ):
                accepting = False
                expected_total, captured_total = validate_captured_pages(pages)
                batch = await asyncio.to_thread(
                    store.complete_batch,
                    batch_sequence,
                    len(pages),
                    expected_total=expected_total,
                    captured_total=captured_total,
                    terminal_confirmed=True,
                )
                return SampleRawCaptureBatch(batch, tuple(pages), False)
        raise RuntimeError("Sample review pagination exceeded the safety limit")
    finally:
        accepting = False
        page.remove_listener("response", schedule)
        if reused:
            page.remove_listener("request", started)
        if tasks:
            for task in tuple(tasks):
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)


async def _read_response(
    response: Response,
    page: Page,
    platform_shop_id: str,
    store: SampleRawBatchStore,
    batch_sequence: int,
    page_sequence: int,
    marker: SampleRawRequestMarker | Exception,
    queue: asyncio.Queue[_CapturedPage | Exception],
    observed_at: datetime,
) -> None:
    try:
        if isinstance(marker, Exception):
            raise marker
        if response.status in {401, 403}:
            raise RuntimeError("Sample browser session expired")
        if not _sample_page_matches(page.url, platform_shop_id):
            raise RuntimeError("Sample response page shop mismatch")
        content_type = await response.header_value("content-type")
        if response.status != 200 or not (content_type or "").casefold().startswith(
            "application/json"
        ):
            raise RuntimeError("Sample response payload is unavailable")
        payload = await response.json()
        if not isinstance(payload, Mapping):
            raise TypeError("Sample response payload is invalid")
        metadata = await read_response_metadata(response, payload)
        await asyncio.to_thread(
            store.persist_page,
            batch_sequence,
            page_sequence,
            payload,
            request_id=metadata.request_id,
            request_page=marker.page,
            request_cursor=marker.cursor,
            response_has_more=metadata.has_more,
            response_total_count=metadata.total_count,
            response_observed_at=observed_at,
        )
        await put_with_backpressure(
            queue,
            _CapturedPage(
                page_sequence,
                parse_hubstudio_sample_response(
                    payload,
                    platform_request_id=None,
                    observed_at=observed_at,
                ),
            ),
        )
    except Exception as error:  # noqa: BLE001 -- untrusted network boundary
        await put_with_backpressure(queue, error)


async def _receive(
    queue: asyncio.Queue[_CapturedPage | Exception],
    buffered: dict[int, TikTokSampleApplicationPage],
    expected: int,
    timeout: float,
) -> TikTokSampleApplicationPage:
    if expected in buffered:
        return buffered.pop(expected)
    while True:
        try:
            result = await asyncio.wait_for(queue.get(), timeout)
        except TimeoutError as error:
            raise TimeoutError(
                "No review request-date response from owned page"
            ) from error
        if isinstance(result, Exception):
            raise result
        if result.sequence == expected:
            return result.page
        buffered[result.sequence] = result.page


def _recover(store: SampleRawBatchStore) -> SampleRawCaptureBatch | None:
    batch = store.recover_completed()
    if batch is None:
        return None
    pages = tuple(
        parse_hubstudio_sample_response(
            item.payload,
            platform_request_id=item.request_id,
            observed_at=item.response_observed_at,
        )
        for item in store.load_pages(batch)
    )
    return SampleRawCaptureBatch(batch, pages, True)
