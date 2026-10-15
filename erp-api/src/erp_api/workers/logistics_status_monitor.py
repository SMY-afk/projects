"""Dedicated logistics polling; independent of page visits and shared workers."""

import asyncio
import json
import logging
import sys
import time
from datetime import UTC, datetime
from uuid import UUID

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from erp_api.core.config import get_settings
from erp_api.main import app
from erp_api.models.order import Order
from erp_api.models.shop import Shop
from erp_api.services.logistics_feishu_source import save_snapshot, snapshot_key
from erp_api.services.logistics_order_alerts import ACTIVE_STATUSES, warning_snapshot
from erp_api.services.logistics_order_categories import (
    category_condition,
    delivered_since,
)
from erp_api.services.tiktok_transport import TikTokClientError
from erp_api.workers.logistics_feishu_job import feishu_loop

HEARTBEAT = "logistics:monitor:"
logger = logging.getLogger("erp_api.logistics_monitor")
MONITOR_ERRORS = (
    RuntimeError,
    OSError,
    ValueError,
    LookupError,
    TimeoutError,
    RedisError,
    SQLAlchemyError,
    TikTokClientError,
)


def pick_tracking_batch(rows, cached, retries, now, *, warm_ids=frozenset()):
    """Rotate unfinished orders every five minutes and warm delivered timestamps."""
    active, delivered = [], []
    for row in rows:
        snapshot = cached.get(row.id, {})
        checked = (
            datetime.fromisoformat(snapshot["checkedAt"]).timestamp()
            if snapshot.get("ruleVersion") == 2
            else 0
        )
        if retries.get(row.id, 0) > now:
            continue
        if row.external_status in ACTIVE_STATUSES:
            if row.id in warm_ids:
                checked = 0
            # Old snapshots need the new physical pickup evidence exactly once.
            if checked > now - 300 and "firstLocationAt" in snapshot and "shippedAt" in snapshot:
                continue
            active.append((checked, row.placed_at, row.id))
        elif not snapshot or not snapshot.get("deliveredAt"):
            if checked <= now - 3600:
                delivered.append((checked, row.placed_at, row.id))
    return [item[2] for item in sorted(active)[:30] + sorted(delivered)[:3]]


async def tenants(database):
    async with database.system_session_factory() as session:
        return list(
            await session.scalars(
                select(Shop.tenant_id)
                .where(Shop.platform == "tiktok", Shop.status == "active")
                .distinct()
            )
        )


async def heartbeat(redis, kind, **details):
    await redis.set(
        HEARTBEAT + kind,
        json.dumps(
            {
                "at": datetime.now(UTC).isoformat(),
                **details,
            },
            default=str,
        ),
        ex=600,
    )


async def sync_loop(state, service):
    while True:
        started = time.monotonic()
        try:
            results = []
            for tenant in await tenants(state.database):
                results.extend(await service._realtime.sync_shops(tenant, None))
            await heartbeat(state.redis, "orders", results=results)
        except MONITOR_ERRORS as error:
            await heartbeat(state.redis, "orders", error=type(error).__name__)
            logger.warning("Order monitor cycle failed: %s", type(error).__name__)
        await asyncio.sleep(max(1, 60 - (time.monotonic() - started)))


async def tracking_loop(state, service):
    retries = {}
    while True:
        started = time.monotonic()
        completed = failed = selected = 0
        try:
            for tenant in await tenants(state.database):
                # Scan all active orders by age on every cycle, including startup.
                # No previous-scan timestamp or small API batch can hide a missed deadline.
                scan = await scan_warnings(state, service, tenant)
                warning_ids = [UUID(key) for key in scan["matches"]]
                snapshots = await state.redis.mget([snapshot_key(tenant, identifier) for identifier in warning_ids]) if warning_ids else []
                warm_ids = {identifier for identifier, value in zip(warning_ids, snapshots, strict=True) if not value}
                async for session in state.database.session(tenant):
                    rows = (
                        await session.execute(
                            select(Order.id, Order.external_status, Order.placed_at)
                            .join(Shop, Shop.id == Order.shop_id)
                            .where(
                                Order.tenant_id == tenant,
                                Shop.tenant_id == tenant,
                                Shop.platform == "tiktok",
                                Shop.status == "active",
                                category_condition(None, delivered_since()),
                            )
                        )
                    ).all()
                cached = await service._realtime.cached(
                    tenant, [row.id for row in rows]
                )
                now = datetime.now(UTC).timestamp()
                retries = {key: until for key, until in retries.items() if until > now}
                batch = pick_tracking_batch(rows, cached, retries, now, warm_ids=warm_ids)
                selected += len(batch)
                semaphore = asyncio.Semaphore(3)

                async def update(
                    order_id, tenant=tenant, semaphore=semaphore, retries=retries
                ):
                    nonlocal completed, failed
                    async with semaphore:
                        try:
                            async with asyncio.timeout(90):
                                result = await service.refresh(tenant, order_id)
                                await save_snapshot(state.redis, tenant, order_id, result)
                            completed += 1
                        except MONITOR_ERRORS as error:
                            failed += 1
                            retries[order_id] = datetime.now(UTC).timestamp() + 300
                            logger.warning(
                                "Tracking monitor query failed: %s",
                                type(error).__name__,
                            )

                await asyncio.gather(*(update(order_id) for order_id in batch))
            await heartbeat(
                state.redis,
                "tracking",
                selected=selected,
                completed=completed,
                failed=failed,
            )
        except MONITOR_ERRORS as error:
            await heartbeat(state.redis, "tracking", error=type(error).__name__)
            logger.warning("Tracking monitor cycle failed: %s", type(error).__name__)
        await asyncio.sleep(max(1, 30 - (time.monotonic() - started)))


async def scan_warnings(state, service, tenant):
    async for session in state.database.session(tenant):
        matches, summary = await warning_snapshot(
            session, tenant, None, None, service._realtime,
            lead_hours=service._repository._alert_settings.read(tenant).leadHours,
        )
    payload = {**summary, "matches": {str(order): flags for order, flags in matches.items()}}
    await state.redis.set(HEARTBEAT + "alerts:" + str(tenant), json.dumps(payload, default=str), ex=600)
    return payload


async def run():
    state = app.state
    service = state.logistics_order_status_service
    if service is None or state.order_sync_service is None:
        raise RuntimeError("Official logistics integration is unavailable")
    service.configure_realtime(state.order_sync_service, state.redis)
    try:
        await asyncio.gather(sync_loop(state, service), tracking_loop(state, service), feishu_loop(state, service))
    finally:
        await state.redis.aclose()
        await state.database.dispose()


async def health():
    redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    try:
        values = await redis.mget([HEARTBEAT + "orders", HEARTBEAT + "tracking"])
        for value in values:
            if not value:
                return False
            status = json.loads(value)
            if (
                "error" in status
                or (
                    datetime.now(UTC) - datetime.fromisoformat(status["at"])
                ).total_seconds()
                > 300
            ):
                return False
        return True
    finally:
        await redis.aclose()


if __name__ == "__main__":
    if "--health" in sys.argv:
        sys.exit(0 if asyncio.run(health()) else 1)
    asyncio.run(run())
