from __future__ import annotations

from datetime import date
from uuid import UUID

from playwright.async_api import BrowserContext

from backend.app.services.affiliate_capture_health_monitor import (
    AVAILABILITY_RESOURCES,
    detect_initial_selectable_dates,
    merge_latest_available_dates,
)
from erp_api.infrastructure.database import Database
from erp_api.services.affiliate_capture_health import AffiliateCaptureHealthRepository
from erp_api.services.affiliate_center_read_repository import (
    AffiliateCenterReadRepository,
)


async def restore_capture_available_dates(
    database: Database,
    health_repository: AffiliateCaptureHealthRepository,
    contexts: list[BrowserContext],
    tenant_id: UUID,
    shop_id: UUID,
) -> dict[str, date]:
    current_health = await health_repository.get(tenant_id, shop_id)
    persisted = await AffiliateCenterReadRepository(database).latest_available_dates(
        tenant_id,
        shop_id,
    )
    available = merge_latest_available_dates(
        current_health.latest_available_dates,
        persisted,
    )
    # Persisted dates describe completed coverage, not necessarily the newest
    # date currently exposed by TikTok. Re-probe both resources on every
    # connection so a restarted listener cannot keep reporting a stale source
    # date merely because the database already contains a complete snapshot.
    detected = await detect_initial_selectable_dates(
        contexts,
        resources=AVAILABILITY_RESOURCES,
    )
    for resource, day in detected.items():
        await health_repository.record_observation(tenant_id, shop_id, resource, day)
    return merge_latest_available_dates(available, detected)
