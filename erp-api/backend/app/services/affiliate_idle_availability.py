from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

from playwright.async_api import BrowserContext, async_playwright

from backend.app.services import hubstudio_attached_browser as attached_browser
from backend.app.services import tiktok_affiliate_page_hygiene as page_hygiene
from backend.app.services.affiliate_capture_health_monitor import (
    AVAILABILITY_RESOURCES,
    detect_initial_selectable_dates,
)
from backend.app.services.tiktok_affiliate_analytics_page_control import (
    is_affiliate_host,
)
from erp_api.infrastructure.database import Database
from erp_api.services.affiliate_capture_health import AffiliateCaptureHealthRepository


async def refresh_idle_availability(
    cdp_url: str,
    tenant_id: UUID,
    shop_id: UUID,
    expected_platform_shop_id: str,
    _database: Database,
    repository: AffiliateCaptureHealthRepository,
) -> dict[str, date]:
    async with async_playwright() as playwright:
        browser = await attached_browser.connect_attached_hubstudio_browser(
            playwright,
            cdp_url,
        )
        platform_shop_ids = _visible_affiliate_shop_ids(browser.contexts)
        if platform_shop_ids != frozenset({expected_platform_shop_id}):
            raise RuntimeError("Browser shop identity is missing or ambiguous.")
        created_pages = await page_hygiene.ensure_affiliate_resource_pages(
            browser.contexts
        )
        try:
            detected = await detect_initial_selectable_dates(
                browser.contexts,
                resources=AVAILABILITY_RESOURCES,
            )
            current = await repository.get(tenant_id, shop_id)
            available = validate_detected_dates(
                current.latest_available_dates,
                detected,
            )
            await repository.record(
                tenant_id,
                shop_id,
                "online",
                latest_available_date=min(available.values()) if available else None,
                latest_available_dates=available,
            )
            for resource, day in detected.items():
                await repository.record_observation(tenant_id, shop_id, resource, day)
            return available
        finally:
            await page_hygiene.close_collector_pages(created_pages)


def _visible_affiliate_shop_ids(contexts: list[BrowserContext]) -> frozenset[str]:
    shop_ids = set()
    for context in contexts:
        for page in context.pages:
            parsed = urlsplit(page.url)
            if not is_affiliate_host(parsed.hostname):
                continue
            shop_ids.update(
                value for value in parse_qs(parsed.query).get("shop_id", []) if value
            )
    return frozenset(shop_ids)


def validate_detected_dates(
    current: Mapping[str, date],
    detected: Mapping[str, date],
) -> dict[str, date]:
    missing = [
        resource for resource in AVAILABILITY_RESOURCES if resource not in detected
    ]
    if missing:
        raise RuntimeError(
            "Live availability detection is incomplete: " + ", ".join(missing)
        )
    for resource in AVAILABILITY_RESOURCES:
        previous = current.get(resource)
        if previous is not None and detected[resource] < previous:
            raise RuntimeError(f"Live availability date regressed: {resource}")
    return {resource: detected[resource] for resource in AVAILABILITY_RESOURCES}


def availability_probe_stagger_seconds(shop_id: UUID) -> float:
    """Spread independent browser probes across the first four minutes."""
    return float(int.from_bytes(shop_id.bytes, "big") % 240)
