from __future__ import annotations

import argparse
import asyncio
import os
import platform
import sys
from datetime import UTC, datetime

# Python 3.13 queries WMI while importing SQLAlchemy. A degraded WMI provider
# must not block this isolated Ziniao worker before it reaches the browser.
if os.name == "nt" and sys.version_info >= (3, 13):
    platform._wmi = None  # type: ignore[attr-defined]

from redis.asyncio import Redis
from sqlalchemy import select

from backend.app.services.affiliate_idle_availability import (
    availability_probe_stagger_seconds,
    refresh_idle_availability,
)
from backend.app.services.capture_logging import capture_log
from backend.app.services.tiktok_affiliate_capture import run_capture_session
from erp_api.core.config import get_settings
from erp_api.infrastructure.database import Database
from erp_api.models.shop import Shop
from erp_api.services.affiliate_capture_health import AffiliateCaptureHealthRepository
from erp_api.services.affiliate_capture_intent_repository import (
    AffiliateCaptureIntentRepository,
)
from erp_api.services.affiliate_sample_priority import (
    sample_round_releases_affiliate,
)
from erp_api.services.affiliate_schedule_queries import (
    daily_retry_window_open,
)
from scripts.run_ziniao_creator_rolling import _ensure_browser

SHOP_NAME = "Akeleo Toys"
DEFAULT_RETRY_DELAYS = (30.0, 60.0, 300.0)
DEFAULT_CAPTURE_SESSION_BATCH_SIZE = 1
IDLE_AVAILABILITY_INTERVAL_SECONDS = 300.0


async def run_watch(
    reconnect_delay: float,
    retry_delays: tuple[float, ...] = DEFAULT_RETRY_DELAYS,
) -> None:
    _configure_capture_session_defaults()
    settings = get_settings()
    database = Database(settings.database_url)
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    health = AffiliateCaptureHealthRepository(redis)
    intents = AffiliateCaptureIntentRepository(database)
    retries_used = 0
    next_availability_probe = 0.0
    try:
        shop = await _shop(database)
        while True:
            now = datetime.now(UTC)
            queued = await intents.next_queued(
                shop.tenant_id, frozenset({shop.platform_shop_id})
            )
            if queued is None:
                cdp_url = await _record_idle_health(settings, shop, health)
                monotonic_now = asyncio.get_running_loop().time()
                window_open = daily_retry_window_open(now)
                if not window_open:
                    next_availability_probe = 0.0
                elif next_availability_probe == 0.0:
                    next_availability_probe = monotonic_now + (
                        availability_probe_stagger_seconds(shop.id)
                    )
                if (
                    cdp_url is not None
                    and window_open
                    and monotonic_now >= next_availability_probe
                ):
                    next_availability_probe = (
                        monotonic_now + IDLE_AVAILABILITY_INTERVAL_SECONDS
                    )
                    await _probe_idle_availability(
                        cdp_url,
                        shop,
                        database,
                        health,
                    )
                await asyncio.sleep(reconnect_delay)
                continue
            if not await sample_round_releases_affiliate(
                database,
                shop.tenant_id,
                shop.id,
                now=datetime.now(UTC),
            ):
                capture_log(
                    "ziniao_affiliate_listener_waiting_for_sample_round",
                    shop_id=shop.id,
                )
                await _record_idle_health(settings, shop, health)
                await asyncio.sleep(reconnect_delay)
                continue
            try:
                browser = await _ensure_browser(settings)
                await health.record(shop.tenant_id, shop.id, "connecting")
                disconnected = await run_capture_session(
                    f"http://127.0.0.1:{browser.debugging_port}",
                    shop.tenant_id,
                    shop.id,
                    database,
                    health_repository=health,
                )
                if disconnected:
                    raise ConnectionError("Ziniao CDP connection was disconnected.")
                retries_used = 0
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001 -- reconnect boundary
                await health.record(shop.tenant_id, shop.id, "browser_offline")
                capture_log(
                    "ziniao_affiliate_listener_failed",
                    shop_id=shop.id,
                    error_type=type(error).__name__,
                )
                delay = _next_retry_delay(retries_used, retry_delays)
                if delay is None:
                    capture_log(
                        "ziniao_affiliate_listener_retry_exhausted",
                        shop_id=shop.id,
                        retry_count=retries_used,
                    )
                    return
                retries_used += 1
                capture_log(
                    "ziniao_affiliate_listener_retry_scheduled",
                    shop_id=shop.id,
                    retry_number=retries_used,
                    delay_seconds=delay,
                )
                await asyncio.sleep(delay)
                continue
            await asyncio.sleep(reconnect_delay)
    finally:
        await redis.aclose()
        await database.dispose()


def _next_retry_delay(
    retries_used: int, retry_delays: tuple[float, ...]
) -> float | None:
    if retries_used < 0 or len(retry_delays) > 3:
        raise ValueError("retry_delays must contain at most three retries")
    if any(delay <= 0 for delay in retry_delays):
        raise ValueError("retry delays must be positive")
    return retry_delays[retries_used] if retries_used < len(retry_delays) else None


def _configure_capture_session_defaults() -> None:
    os.environ.setdefault(
        "AFFILIATE_CAPTURE_SESSION_BATCH_SIZE",
        str(DEFAULT_CAPTURE_SESSION_BATCH_SIZE),
    )


async def _record_idle_health(
    settings,
    shop: Shop,
    health: AffiliateCaptureHealthRepository,
) -> str | None:
    try:
        browser = await _ensure_browser(settings)
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 -- keep idle health truthful
        state = "browser_offline"
        cdp_url = None
    else:
        state = "online"
        cdp_url = f"http://127.0.0.1:{browser.debugging_port}"
    await health.record(shop.tenant_id, shop.id, state)
    return cdp_url


async def _probe_idle_availability(cdp_url, shop, database, health) -> None:
    try:
        await refresh_idle_availability(
            cdp_url,
            shop.tenant_id,
            shop.id,
            shop.platform_shop_id,
            database,
            health,
        )
    except asyncio.CancelledError:
        raise
    except Exception as error:  # noqa: BLE001 -- next idle probe retries safely
        capture_log(
            "ziniao_idle_availability_failed",
            shop_id=shop.id,
            error_type=type(error).__name__,
        )


async def _shop(database: Database) -> Shop:
    async with database.system_session_factory() as session:
        rows = (
            await session.scalars(
                select(Shop).where(
                    Shop.shop_name == SHOP_NAME,
                    Shop.platform == "tiktok",
                    Shop.status == "active",
                )
            )
        ).all()
    if len(rows) != 1:
        raise RuntimeError("Akeleo Toys must resolve to one active TikTok shop.")
    return rows[0]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Keep the Akeleo Toys Ziniao affiliate listener running."
    )
    parser.add_argument("--reconnect-delay", type=float, default=5)
    args = parser.parse_args()
    if args.reconnect_delay <= 0:
        parser.error("--reconnect-delay must be greater than zero")
    asyncio.run(run_watch(args.reconnect_delay))


if __name__ == "__main__":
    main()
