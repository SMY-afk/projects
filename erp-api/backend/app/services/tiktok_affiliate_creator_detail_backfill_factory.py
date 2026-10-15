from __future__ import annotations

import os
from uuid import UUID

from backend.app.services.tiktok_affiliate_creator_concurrency import (
    MAX_AFFILIATE_CONCURRENCY,
)
from backend.app.services.tiktok_affiliate_creator_detail_backfill import (
    TikTokAffiliateCreatorDetailBackfill,
)
from backend.app.services.tiktok_affiliate_creator_detail_capture import (
    TikTokAffiliateCreatorDetailCapture,
)
from erp_api.infrastructure.database import Database


def build_creator_detail_backfill(
    tenant_id: UUID,
    database: Database,
    capture: TikTokAffiliateCreatorDetailCapture,
) -> TikTokAffiliateCreatorDetailBackfill:
    return TikTokAffiliateCreatorDetailBackfill(
        tenant_id,
        database,
        capture,
        max_creators=int(os.getenv("AFFILIATE_DETAIL_BACKFILL_MAX_CREATORS", "5000")),
        max_pages=int(os.getenv("AFFILIATE_DETAIL_BACKFILL_MAX_PAGES", "500")),
        max_runtime_seconds=float(
            os.getenv("AFFILIATE_DETAIL_BACKFILL_MAX_RUNTIME_SECONDS", "10800")
        ),
        min_request_interval=float(
            os.getenv("AFFILIATE_DETAIL_BACKFILL_REQUEST_INTERVAL", "0.8")
        ),
        concurrency=_affiliate_concurrency(),
        stale_after_hours=_affiliate_stale_hours(),
        creator_usernames=_creator_usernames(),
    )


def _affiliate_concurrency() -> int:
    configured = int(os.getenv("AFFILIATE_CONCURRENCY", "5"))
    return min(max(configured, 1), MAX_AFFILIATE_CONCURRENCY)


def _affiliate_stale_hours() -> float:
    configured = float(os.getenv("AFFILIATE_CREATOR_STALE_HOURS", "24"))
    if configured <= 0:
        raise ValueError("AFFILIATE_CREATOR_STALE_HOURS must be positive.")
    return configured


def _creator_usernames() -> frozenset[str]:
    raw = os.getenv("AFFILIATE_DETAIL_CREATOR_USERNAMES", "")
    return frozenset(
        value.strip().lstrip("@").casefold()
        for value in raw.split(",")
        if value.strip()
    )
