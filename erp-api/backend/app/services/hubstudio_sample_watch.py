from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
from time import monotonic
from urllib.parse import parse_qs, urlencode, urlsplit

from playwright.async_api import BrowserContext, Page, Playwright
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from backend.app.services.capture_logging import capture_log
from backend.app.services.hubstudio_attached_browser import (
    connect_attached_hubstudio_browser,
)
from backend.app.services.hubstudio_sample_network_listener import (
    HubStudioSampleNetworkListener,
)
from backend.app.services.sample_request_page_controls import (
    next_sample_page,
    prepare_sample_review_page,
)
from backend.app.services.sample_watch_error_category import classify_watch_error
from erp_api.services.hubstudio_sample_application_source import (
    HubStudioSamplePreflight,
)

SAMPLE_PAGE_HOST = "affiliate.tiktokshopglobalselling.com"
SAMPLE_PAGE_HOSTS = frozenset({SAMPLE_PAGE_HOST, "affiliate-us.tiktok.com"})
SAMPLE_PAGE_PATH = "/affiliate/sample/sample-request"
SAMPLE_ERROR_PAGE_PATH = "/errorpage"
MAX_SAMPLE_BROWSER_TABS = 8
DEFAULT_CAPTURE_TIMEOUT_SECONDS = 120.0
DEFAULT_PROCESSING_TIMEOUT_SECONDS = 600.0
PAGE_PREPARATION_GRACE_SECONDS = 240.0
STATUS_TAB_READY_TIMEOUT_MS = 120_000


@dataclass
class _CycleState:
    event: asyncio.Event
    ingest_result: object | None = None
    sync_result: object | None = None
    profile_captured: int = 0
    profile_error_type: str | None = None
    processing_error_type: str | None = None


@dataclass(frozen=True)
class _CaptureProcessingResult:
    sync_result: object | None
    profile_captured: int
    profile_error_type: str | None
    processing_error_type: str | None = None


async def run_hubstudio_sample_watch(
    *,
    playwright: Playwright,
    source,
    preflight: HubStudioSamplePreflight,
    ingest_service,
    profile_target_provider,
    profile_collector,
    feishu_sync_service,
    post_source_service=None,
    shop_sync_lock=None,
    interval_seconds: float,
    once: bool = False,
    max_cycles: int | None = None,
    capture_timeout_seconds: float = DEFAULT_CAPTURE_TIMEOUT_SECONDS,
    processing_timeout_seconds: float = DEFAULT_PROCESSING_TIMEOUT_SECONDS,
) -> str:
    if (
        interval_seconds <= 0
        or capture_timeout_seconds <= 0
        or processing_timeout_seconds <= 0
        or (max_cycles is not None and max_cycles < 1)
    ):
        raise ValueError("Sample watch intervals must be positive.")
    target = preflight.target
    attached = await connect_attached_hubstudio_browser(
        playwright, preflight.normalized_cdp_url
    )
    if not attached.contexts:
        raise RuntimeError("HubStudio browser has no available context.")
    disconnected = asyncio.Event()
    attached.on("disconnected", lambda *_: disconnected.set())
    cycle = _CycleState(asyncio.Event())

    async def handle_capture(capture) -> None:
        cycle.ingest_result = await ingest_service.ingest_page(capture)
        cycle.event.set()
        if cycle.ingest_result.status != "succeeded":
            return
        result = await _capture_profiles_then_sync(
            capture,
            contexts=attached.contexts,
            profile_target_provider=profile_target_provider,
            profile_collector=profile_collector,
            feishu_sync_service=feishu_sync_service,
            post_source_service=post_source_service,
            shop_sync_lock=shop_sync_lock,
            source_result=cycle.ingest_result,
        )
        cycle.sync_result = result.sync_result
        cycle.profile_captured = result.profile_captured
        cycle.profile_error_type = result.profile_error_type
        cycle.processing_error_type = result.processing_error_type

    listener = HubStudioSampleNetworkListener(
        preflight,
        handle_capture,
        stop_handler=lambda reason: ingest_service.abort(target, reason),
        source_guard=lambda: source.revalidate(preflight),
    )
    listener.attach(attached.contexts)
    completed_cycles = 0
    while not disconnected.is_set() and not listener.is_stopped:
        started = monotonic()
        try:
            status = await asyncio.wait_for(
                _run_cycle(
                    attached.contexts,
                    target,
                    cycle,
                    listener,
                    disconnected,
                    capture_timeout_seconds,
                ),
                timeout=capture_timeout_seconds + PAGE_PREPARATION_GRACE_SECONDS,
            )
        except (TimeoutError, PlaywrightTimeoutError):
            status = "page_prepare_timeout"
        if not await _wait_for_processing(listener, processing_timeout_seconds):
            status = "processing_timeout"
        elif cycle.processing_error_type is not None:
            status = "processing_failed"
        if listener.is_stopped:
            status = listener.stop_reason or status
        _log_cycle(target, status, cycle)
        completed_cycles += 1
        if once:
            return status
        remaining = interval_seconds - (monotonic() - started)
        if max_cycles is not None and completed_cycles >= max_cycles:
            if listener.is_stopped or disconnected.is_set():
                break
            if remaining > 0:
                await asyncio.sleep(remaining)
            return "recycle"
        if remaining > 0:
            await asyncio.sleep(remaining)
    await listener.wait_for_pending()
    reason = listener.stop_reason or "cdp_disconnected"
    await ingest_service.abort(target, reason)
    return reason


async def _capture_profiles_then_sync(
    capture,
    *,
    contexts,
    profile_target_provider,
    profile_collector,
    feishu_sync_service,
    post_source_service=None,
    shop_sync_lock=None,
    source_result=None,
) -> _CaptureProcessingResult:
    sync_result = None
    profile_captured = 0
    profile_error_type = None

    async def capture_profiles() -> None:
        nonlocal profile_captured, profile_error_type
        try:
            targets = await profile_target_provider.list_targets(capture)
            profile_captured = await profile_collector.capture(contexts, targets)
        except Exception as error:  # noqa: BLE001 -- profile gaps do not block assignment
            profile_error_type = type(error).__name__

    if post_source_service is None:
        await capture_profiles()
        sync_result = await feishu_sync_service.sync(
            tenant_id=capture.target.tenant_id,
            shop_id=capture.target.shop_id,
        )
    else:
        try:
            async def complete_pipeline():
                return await post_source_service.complete_after_source(
                    tenant_id=capture.target.tenant_id,
                    shop_id=capture.target.shop_id,
                    source_type="hubstudio_cdp",
                    source_results=(
                        (source_result,) if source_result is not None else ()
                    ),
                    profile_capture=capture_profiles,
                )

            if shop_sync_lock is None:
                pipeline_result = await complete_pipeline()
            else:
                async with shop_sync_lock.acquire(
                    capture.target.tenant_id, capture.target.shop_id
                ) as acquired:
                    if not acquired:
                        capture_log(
                            "hubstudio_sample_sync_deferred",
                            tenant_id=capture.target.tenant_id,
                            shop_id=capture.target.shop_id,
                            reason="shop_sync_busy",
                        )
                        return _CaptureProcessingResult(
                            sync_result,
                            profile_captured,
                            profile_error_type,
                        )
                    pipeline_result = await complete_pipeline()
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 -- retry on the next watch cycle
            category, code = classify_watch_error(error)
            capture_log(
                "hubstudio_sample_post_source_failed",
                shop_id=capture.target.shop_id,
                error_type=type(error).__name__,
                error_category=category,
                error_code=code,
            )
            return _CaptureProcessingResult(
                sync_result,
                profile_captured,
                profile_error_type,
                type(error).__name__,
            )
        sync_result = pipeline_result.feishu_result
    return _CaptureProcessingResult(
        sync_result,
        profile_captured,
        profile_error_type,
    )


async def _run_cycle(
    contexts: list[BrowserContext],
    target,
    cycle: _CycleState,
    listener: HubStudioSampleNetworkListener,
    disconnected: asyncio.Event,
    timeout_seconds: float,
) -> str:
    cycle.ingest_result = None
    cycle.sync_result = None
    cycle.profile_captured = 0
    cycle.profile_error_type = None
    cycle.processing_error_type = None
    cycle.event.clear()
    page = await _load_first_page(contexts, target)
    while True:
        event_status = await _wait_for_event(
            cycle.event, listener, disconnected, timeout_seconds
        )
        if event_status != "capture":
            if event_status != "capture_timeout":
                await listener.stop(event_status)
            return event_status
        result = cycle.ingest_result
        if result is None:
            await listener.stop("ingest_result_missing")
            return "ingest_result_missing"
        if result.status != "running":
            return result.status
        await listener.wait_for_pending()
        cycle.event.clear()
        if not await next_sample_page(page):
            await listener.stop("pagination_control_missing")
            return "pagination_control_missing"


async def _wait_for_event(
    event: asyncio.Event,
    listener: HubStudioSampleNetworkListener,
    disconnected: asyncio.Event,
    timeout_seconds: float,
) -> str:
    event_task = asyncio.create_task(event.wait())
    stopped_task = asyncio.create_task(listener.wait_stopped())
    disconnected_task = asyncio.create_task(disconnected.wait())
    done, pending = await asyncio.wait(
        {event_task, stopped_task, disconnected_task},
        timeout=timeout_seconds,
        return_when=asyncio.FIRST_COMPLETED,
    )
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)
    if event_task in done and event.is_set():
        return "capture"
    if stopped_task in done:
        return listener.stop_reason or "listener_stopped"
    if disconnected_task in done:
        return "cdp_disconnected"
    return "capture_timeout"


async def _load_first_page(contexts: list[BrowserContext], target) -> Page:
    page = next(
        (
            page
            for context in contexts
            for page in context.pages
            if _sample_page_matches(page.url, target.platform_shop_id)
        ),
        None,
    )
    created = page is None
    if created and len(contexts[0].pages) >= MAX_SAMPLE_BROWSER_TABS:
        raise RuntimeError("tab_limit_reached")
    try:
        if created:
            page = await contexts[0].new_page()
            url = _sample_page_url(target.platform_shop_id)
            await page.goto(url, wait_until="domcontentloaded")
        else:
            try:
                await page.reload(wait_until="domcontentloaded")
            except PlaywrightTimeoutError:
                if not _sample_page_matches(page.url, target.platform_shop_id):
                    raise
        if _sample_error_page_matches(page.url):
            raise RuntimeError("Sample request page redirected to an error page.")
        await prepare_sample_review_page(page)
        return page
    except BaseException:
        if page is not None and (created or _sample_error_page_matches(page.url)):
            with suppress(Exception):
                await page.close()
        raise


async def _wait_for_processing(listener, timeout_seconds: float) -> bool:
    try:
        await asyncio.wait_for(listener.wait_for_pending(), timeout=timeout_seconds)
    except TimeoutError:
        return False
    return True


def _sample_page_matches(url: str, platform_shop_id: str) -> bool:
    split = urlsplit(url)
    return (
        split.hostname in SAMPLE_PAGE_HOSTS
        and split.path == SAMPLE_PAGE_PATH
        and parse_qs(split.query).get("shop_id") == [platform_shop_id]
    )


def _sample_error_page_matches(url: str) -> bool:
    split = urlsplit(url)
    return split.hostname in SAMPLE_PAGE_HOSTS and split.path == SAMPLE_ERROR_PAGE_PATH


def _sample_page_url(platform_shop_id: str) -> str:
    query = urlencode({"shop_region": "US", "shop_id": platform_shop_id})
    return f"https://{SAMPLE_PAGE_HOST}{SAMPLE_PAGE_PATH}?{query}"


def _log_cycle(target, status: str, cycle: _CycleState) -> None:
    ingest = cycle.ingest_result
    sync = cycle.sync_result
    capture_log(
        "hubstudio_sample_watch_cycle_completed",
        tenant_id=target.tenant_id,
        shop_id=target.shop_id,
        status=status,
        source_records=getattr(ingest, "record_count", 0),
        feishu_created=getattr(sync, "created_count", 0),
        feishu_updated=getattr(sync, "updated_count", 0),
        profile_captured=cycle.profile_captured,
        profile_error_type=cycle.profile_error_type,
        processing_error_type=cycle.processing_error_type,
    )
