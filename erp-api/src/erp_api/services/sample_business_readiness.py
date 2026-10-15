"""Fail-closed local prerequisites before a pending sample reaches Feishu."""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID

from redis.asyncio import Redis

from erp_api.core.config import get_settings
from erp_api.infrastructure.database import Database
from erp_api.infrastructure.health import probe_dependencies
from erp_api.routers.health import _sample_sync_config_status
from erp_api.services.daily_valid_creator_schedule import (
    daily_valid_creator_source_batch,
)
from scripts.sample_watch_freshness import SHOPS, TENANT_ID, build_report

SAMPLE_SOURCE_STALE_SECONDS = 900

_REQUIRED_DEPENDENCIES = (
    "database",
    "redis",
    "sample_sync_config",
    "sample_schema",
    "sample_worker",
)


class SampleBusinessReadiness:
    """Validate the last due daily batch only when local pending work exists."""

    async def require_ready(self, *, tenant_id: UUID, shop_id: UUID) -> None:
        labels = [label for label, configured_id in SHOPS.items() if configured_id == shop_id]
        if tenant_id != TENANT_ID or len(labels) != 1:
            raise RuntimeError("sample_business_readiness:shop_scope_incomplete")
        await self._require_readyz()
        report = await build_report(SAMPLE_SOURCE_STALE_SECONDS)
        target = [row for row in report["shops"] if row["shop"] == labels[0]]
        if len(target) != 1 or not target[0]["sample_ok"]:
            raise RuntimeError("sample_business_readiness:sample_source_stale")
        if {row["shop"] for row in report["shops"]} != set(SHOPS):
            raise RuntimeError("sample_business_readiness:shop_scope_incomplete")
        batch_date = _valid_creator_batch_date(datetime.now(UTC))
        # The success receipt is published only after complete five-shop inputs,
        # Feishu apply and zero-difference reread. Later cutoff changes must not
        # invalidate that verified table while the next export is being prepared.
        if not await self._daily_sync_succeeded(batch_date):
            raise RuntimeError("sample_business_readiness:valid_creator_sync_missing")

    @staticmethod
    async def _require_readyz() -> None:
        settings = get_settings()
        if _sample_sync_config_status(settings) != "ok":
            raise RuntimeError("sample_business_readiness:readyz_unhealthy")
        database = Database(settings.database_url)
        try:
            dependencies = await probe_dependencies(
                database, settings.redis_url, sample_sync_enabled=True
            )
        finally:
            await database.dispose()
        if any(dependencies.get(key) != "ok" for key in _REQUIRED_DEPENDENCIES):
            raise RuntimeError("sample_business_readiness:readyz_unhealthy")

    @staticmethod
    async def _daily_sync_succeeded(batch_date: date) -> bool:
        redis = Redis.from_url(get_settings().redis_url)
        try:
            pattern = f"valid-creator-sync:{batch_date:%Y%m%d}:*:success"
            async for _ in redis.scan_iter(match=pattern, count=20):
                return True
            return False
        finally:
            await redis.aclose()


def _valid_creator_batch_date(now: datetime) -> date:
    """Keep the prior verified table until the independent 01:30 write is due."""
    return daily_valid_creator_source_batch(now)
