from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable
from datetime import date
from uuid import UUID

from playwright.async_api import BrowserContext, Page

from backend.app.services.affiliate_available_date_merge import (
    merge_latest_available_dates,
)
from backend.app.services.capture_logging import capture_log as _log
from backend.app.services.tiktok_affiliate_analytics_page_control import (
    is_affiliate_host,
    page_security_failure,
)
from backend.app.services.tiktok_affiliate_available_date import (
    detect_latest_selectable_dates,
)
from erp_api.services.affiliate_capture_health import (
    AffiliateCaptureHealthRepository,
    CaptureHealthState,
)

HEARTBEAT_INTERVAL_SECONDS = 10.0
HEARTBEAT_OPERATION_TIMEOUT_SECONDS = 5.0
PAGE_SECURITY_PROBE_TIMEOUT_SECONDS = 1.0
AVAILABILITY_REFRESH_INTERVAL_SECONDS = 300.0
INITIAL_AVAILABILITY_TIMEOUT_SECONDS = 45.0
INITIAL_AVAILABILITY_ATTEMPTS = 2
INITIAL_AVAILABILITY_RETRY_DELAY_SECONDS = 1.0
AVAILABILITY_RESOURCE_TIMEOUT_SECONDS = 20.0
AVAILABILITY_RETRY_DELAY_SECONDS = 1.0
AVAILABILITY_RESOURCES = ("creators", "videos")
AvailabilityDetector = Callable[
    [Iterable[BrowserContext], tuple[str, ...]], Awaitable[dict[str, date]]
]


async def detect_initial_selectable_dates(
    contexts: Iterable[BrowserContext],
    *,
    resources: tuple[str, ...] = AVAILABILITY_RESOURCES,
    timeout_seconds: float = INITIAL_AVAILABILITY_TIMEOUT_SECONDS,
    attempts: int = INITIAL_AVAILABILITY_ATTEMPTS,
    retry_delay_seconds: float = INITIAL_AVAILABILITY_RETRY_DELAY_SECONDS,
    detector: AvailabilityDetector = detect_latest_selectable_dates,
) -> dict[str, date]:
    if timeout_seconds <= 0:
        raise ValueError("Initial availability timeout must be positive.")
    if attempts <= 0 or retry_delay_seconds < 0:
        raise ValueError(
            "Availability attempts must be positive and delay non-negative."
        )
    context_list = list(contexts)

    async def detect_resource(resource: str) -> dict[str, date]:
        for attempt in range(attempts):
            try:
                result = await asyncio.wait_for(
                    detector(context_list, (resource,)),
                    timeout=timeout_seconds,
                )
                if resource in result:
                    return result
            except Exception:  # noqa: BLE001,S110 -- retry independently
                pass
            if attempt + 1 < attempts and retry_delay_seconds:
                await asyncio.sleep(retry_delay_seconds)
        return {}

    detected: dict[str, date] = {}
    # These pages share one authenticated browser context. Probing them in
    # parallel causes SPA navigation and date-picker rendering to interfere.
    for resource in resources:
        detected.update(await detect_resource(resource))
    return detected


async def run_capture_health_heartbeat(
    contexts: Iterable[BrowserContext],
    tenant_id: UUID,
    shop_id: UUID,
    repository: AffiliateCaptureHealthRepository,
    stopped: asyncio.Event,
    *,
    interval_seconds: float = HEARTBEAT_INTERVAL_SECONDS,
    operation_timeout_seconds: float = HEARTBEAT_OPERATION_TIMEOUT_SECONDS,
) -> None:
    while not stopped.is_set():
        try:
            state = await asyncio.wait_for(
                browser_capture_state(contexts),
                timeout=operation_timeout_seconds,
            )
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 -- page probe must be bounded
            _log(
                "affiliate_health_probe_failed",
                tenant_id=tenant_id,
                shop_id=shop_id,
                error_type=type(error).__name__,
            )
            state = "connecting"
        try:
            await asyncio.wait_for(
                repository.record(tenant_id, shop_id, state),
                timeout=operation_timeout_seconds,
            )
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 -- heartbeat must self-heal
            _log(
                "affiliate_health_heartbeat_failed",
                tenant_id=tenant_id,
                shop_id=shop_id,
                error_type=type(error).__name__,
            )
        try:
            await asyncio.wait_for(stopped.wait(), timeout=interval_seconds)
        except TimeoutError:
            pass


async def run_connecting_health_heartbeat(
    tenant_id: UUID,
    shop_id: UUID,
    repository: AffiliateCaptureHealthRepository,
    stopped: asyncio.Event,
    *,
    interval_seconds: float = HEARTBEAT_INTERVAL_SECONDS,
    operation_timeout_seconds: float = HEARTBEAT_OPERATION_TIMEOUT_SECONDS,
) -> None:
    """Keep preflight visible without letting a transient write kill the task."""
    while not stopped.is_set():
        try:
            await asyncio.wait_for(
                repository.record(tenant_id, shop_id, "connecting"),
                timeout=operation_timeout_seconds,
            )
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 -- heartbeat must self-heal
            _log(
                "affiliate_connecting_heartbeat_failed",
                tenant_id=tenant_id,
                shop_id=shop_id,
                error_type=type(error).__name__,
            )
        try:
            await asyncio.wait_for(stopped.wait(), timeout=interval_seconds)
        except TimeoutError:
            pass


async def browser_capture_state(
    contexts: Iterable[BrowserContext],
    *,
    page_probe_timeout_seconds: float = PAGE_SECURITY_PROBE_TIMEOUT_SECONDS,
) -> CaptureHealthState:
    if page_probe_timeout_seconds <= 0:
        raise ValueError("Page security probe timeout must be positive.")
    pages: list[Page] = [page for context in contexts for page in context.pages]
    from urllib.parse import urlsplit

    resource_pages = [
        page
        for page in pages
        if is_affiliate_host(urlsplit(page.url).hostname)
    ]
    results = await asyncio.gather(
        *(
            asyncio.wait_for(
                page_security_failure(page),
                timeout=page_probe_timeout_seconds,
            )
            for page in resource_pages or pages
        ),
        return_exceptions=True,
    )
    failures = [result[1] for result in results if isinstance(result, tuple)]
    if "captcha" in failures:
        return "captcha"
    if "session_expired" in failures:
        return "session_expired"
    if not results or any(isinstance(result, BaseException) for result in results):
        return "connecting"
    return "online"


async def run_capture_availability_refresh(
    contexts: Iterable[BrowserContext],
    tenant_id: UUID,
    shop_id: UUID,
    repository: AffiliateCaptureHealthRepository,
    stopped: asyncio.Event,
    mutation_lock: asyncio.Lock,
    *,
    interval_seconds: float = AVAILABILITY_REFRESH_INTERVAL_SECONDS,
    resource_timeout_seconds: float = AVAILABILITY_RESOURCE_TIMEOUT_SECONDS,
    retry_delay_seconds: float = AVAILABILITY_RETRY_DELAY_SECONDS,
    detector: AvailabilityDetector = detect_latest_selectable_dates,
) -> None:
    if interval_seconds <= 0:
        raise ValueError("Availability refresh interval must be positive.")
    if resource_timeout_seconds <= 0:
        raise ValueError("Availability resource timeout must be positive.")
    if retry_delay_seconds < 0:
        raise ValueError("Availability retry delay cannot be negative.")
    context_list = list(contexts)
    while not stopped.is_set():
        try:
            await asyncio.wait_for(stopped.wait(), timeout=interval_seconds)
            return
        except TimeoutError:
            pass
        for resource in AVAILABILITY_RESOURCES:
            try:
                detected = await _detect_resource_with_retry(
                    context_list,
                    resource,
                    detector,
                    mutation_lock,
                    resource_timeout_seconds,
                    retry_delay_seconds,
                )
                if detected is None:
                    _log(
                        "affiliate_availability_refresh_missing",
                        tenant_id=tenant_id,
                        shop_id=shop_id,
                        resource=resource,
                    )
                    continue
                current = await repository.get(tenant_id, shop_id)
                current_date = current.latest_available_dates.get(resource)
                merged = merge_latest_available_dates(
                    current.latest_available_dates,
                    {resource: detected},
                )
                if current_date is not None and detected < current_date:
                    _log(
                        "affiliate_availability_regression_ignored",
                        tenant_id=tenant_id,
                        shop_id=shop_id,
                        resource=resource,
                    )
                    continue
                await repository.record(
                    tenant_id,
                    shop_id,
                    current.state,
                    latest_available_date=min(merged.values()),
                    latest_available_dates=merged,
                )
                await repository.record_observation(
                    tenant_id, shop_id, resource, detected
                )
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001 -- retry this resource later
                _log(
                    "affiliate_availability_refresh_failed",
                    tenant_id=tenant_id,
                    shop_id=shop_id,
                    resource=resource,
                    error_type=type(error).__name__,
                )


async def _detect_resource_with_retry(
    contexts: list[BrowserContext],
    resource: str,
    detector: AvailabilityDetector,
    mutation_lock: asyncio.Lock,
    timeout_seconds: float,
    retry_delay_seconds: float,
) -> date | None:
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            async with mutation_lock:
                result = await asyncio.wait_for(
                    detector(contexts, (resource,)),
                    timeout=timeout_seconds,
                )
            last_error = None
            if detected := result.get(resource):
                return detected
        except Exception as error:  # noqa: BLE001 -- retry one transient page stall
            last_error = error
        if attempt == 0 and retry_delay_seconds:
            await asyncio.sleep(retry_delay_seconds)
    if last_error is not None:
        raise last_error
    return None


