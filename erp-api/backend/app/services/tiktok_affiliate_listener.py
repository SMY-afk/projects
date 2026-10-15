from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID

from redis.asyncio import from_url
from sqlalchemy import select

from backend.app.services.affiliate_idle_availability import (
    availability_probe_stagger_seconds,
    refresh_idle_availability,
)
from backend.app.services.capture_logging import capture_log as _log
from backend.app.services.hubstudio_cdp import (
    discover_hubstudio_cdp_url,
    normalize_loopback_cdp_url,
)
from backend.app.services.hubstudio_cdp_ownership import (
    assert_erp_hubstudio_cdp_url,
)
from erp_api.core.config import get_settings
from erp_api.infrastructure.database import Database
from erp_api.models.shop import Shop
from erp_api.services.affiliate_capture_health import (
    AffiliateCaptureHealthRepository,
)
from erp_api.services.affiliate_capture_intent_repository import (
    AffiliateCaptureIntentRepository,
)
from erp_api.services.affiliate_sample_priority import (
    sample_round_releases_affiliate,
)
from erp_api.services.affiliate_schedule_queries import (
    daily_retry_window_open,
)

DEFAULT_RETRY_DELAYS = (30.0, 60.0, 300.0)
STARTUP_QUERY_TIMEOUT_SECONDS = 10.0
HEALTH_RECORD_TIMEOUT_SECONDS = 5.0
IDLE_POLL_INTERVAL_SECONDS = 30.0
IDLE_AVAILABILITY_INTERVAL_SECONDS = 300.0


async def run_listener(
    cdp_url: str | None,
    tenant_id: UUID,
    shop_id: UUID,
    retry_delays: tuple[float, ...] = DEFAULT_RETRY_DELAYS,
) -> None:
    from backend.app.services.tiktok_affiliate_capture import run_capture_session

    configured_url = normalize_loopback_cdp_url(cdp_url)
    if cdp_url is not None and configured_url is None:
        raise ValueError("HubStudio CDP URL must be a loopback HTTP endpoint.")
    if len(retry_delays) > 3 or any(delay <= 0 for delay in retry_delays):
        raise ValueError("retry_delays must contain at most three positive values")
    settings = get_settings()
    database = Database(settings.database_url)
    redis = from_url(settings.redis_url, decode_responses=True)
    health_repository = AffiliateCaptureHealthRepository(redis)
    intent_repository = AffiliateCaptureIntentRepository(database)
    retries_used = 0
    expected_platform_shop_id: str | None = None
    current_url = configured_url
    next_availability_probe = 0.0
    try:
        while True:
            try:
                if expected_platform_shop_id is None:
                    expected_platform_shop_id = await asyncio.wait_for(
                        _configured_platform_shop_id(database, tenant_id, shop_id),
                        timeout=STARTUP_QUERY_TIMEOUT_SECONDS,
                    )
                platform_shop_ids = frozenset({expected_platform_shop_id})
                now = datetime.now(UTC)
                queued = await intent_repository.next_queued(
                    tenant_id, platform_shop_ids
                )
                if queued is None:
                    current_url = await _record_idle_browser_health(
                        current_url,
                        expected_platform_shop_id,
                        health_repository,
                        tenant_id,
                        shop_id,
                    )
                    monotonic_now = asyncio.get_running_loop().time()
                    window_open = daily_retry_window_open(now)
                    if not window_open:
                        next_availability_probe = 0.0
                    elif next_availability_probe == 0.0:
                        next_availability_probe = monotonic_now + (
                            availability_probe_stagger_seconds(shop_id)
                        )
                    if (
                        current_url is not None
                        and window_open
                        and monotonic_now >= next_availability_probe
                    ):
                        next_availability_probe = (
                            monotonic_now + IDLE_AVAILABILITY_INTERVAL_SECONDS
                        )
                        await _probe_idle_availability(
                            current_url,
                            tenant_id,
                            shop_id,
                            expected_platform_shop_id,
                            database,
                            health_repository,
                        )
                    retries_used = 0
                    await asyncio.sleep(IDLE_POLL_INTERVAL_SECONDS)
                    continue
                if not await sample_round_releases_affiliate(
                    database,
                    tenant_id,
                    shop_id,
                    now=datetime.now(UTC),
                ):
                    _log(
                        "affiliate_syncer_waiting_for_sample_round",
                        tenant_id=tenant_id,
                        shop_id=shop_id,
                    )
                    current_url = await _record_idle_browser_health(
                        current_url,
                        expected_platform_shop_id,
                        health_repository,
                        tenant_id,
                        shop_id,
                    )
                    retries_used = 0
                    await asyncio.sleep(IDLE_POLL_INTERVAL_SECONDS)
                    continue
                resolved_url = await discover_hubstudio_cdp_url(
                    current_url=current_url,
                    expected_platform_shop_id=expected_platform_shop_id,
                )
                if resolved_url is None:
                    raise ConnectionError("HubStudio CDP endpoint is unavailable.")
                owned_url = await asyncio.to_thread(
                    assert_erp_hubstudio_cdp_url, resolved_url
                )
                current_url = owned_url
                await _record_health(
                    health_repository, tenant_id, shop_id, "connecting"
                )
                disconnected = await run_capture_session(
                    resolved_url,
                    tenant_id,
                    shop_id,
                    database,
                    health_repository=health_repository,
                )
                if disconnected:
                    raise ConnectionError("HubStudio CDP connection was disconnected.")
                retries_used = 0
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001 -- reconnect boundary
                await _record_health(
                    health_repository, tenant_id, shop_id, "browser_offline"
                )
                _log(
                    "affiliate_syncer_connection_failed",
                    tenant_id=tenant_id,
                    shop_id=shop_id,
                    error_type=type(error).__name__,
                )
                if retries_used >= len(retry_delays):
                    _log(
                        "affiliate_syncer_retry_exhausted",
                        tenant_id=tenant_id,
                        shop_id=shop_id,
                        retry_count=retries_used,
                    )
                    return
                delay = retry_delays[retries_used]
                retries_used += 1
                _log(
                    "affiliate_syncer_retry_scheduled",
                    tenant_id=tenant_id,
                    shop_id=shop_id,
                    retry_number=retries_used,
                    delay_seconds=delay,
                )
                await asyncio.sleep(delay)
    finally:
        await redis.aclose()
        await database.dispose()


async def _record_idle_browser_health(
    current_url: str | None,
    expected_platform_shop_id: str,
    repository: AffiliateCaptureHealthRepository,
    tenant_id: UUID,
    shop_id: UUID,
) -> str | None:
    try:
        resolved_url = await discover_hubstudio_cdp_url(
            current_url=current_url,
            expected_platform_shop_id=expected_platform_shop_id,
        )
        if resolved_url is None:
            raise ConnectionError("HubStudio CDP endpoint is unavailable.")
        owned_url = await asyncio.to_thread(assert_erp_hubstudio_cdp_url, resolved_url)
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 -- an idle probe must not start capture retries
        await _record_health(repository, tenant_id, shop_id, "browser_offline")
        return current_url
    await _record_health(repository, tenant_id, shop_id, "online")
    return owned_url


async def _record_health(
    repository: AffiliateCaptureHealthRepository,
    tenant_id: UUID,
    shop_id: UUID,
    state: str,
) -> None:
    try:
        await asyncio.wait_for(
            repository.record(tenant_id, shop_id, state),
            timeout=HEALTH_RECORD_TIMEOUT_SECONDS,
        )
    except Exception as error:  # noqa: BLE001 -- observability must not block retries
        _log(
            "affiliate_syncer_health_record_failed",
            tenant_id=tenant_id,
            shop_id=shop_id,
            error_type=type(error).__name__,
        )


async def _probe_idle_availability(
    cdp_url: str,
    tenant_id: UUID,
    shop_id: UUID,
    expected_platform_shop_id: str,
    database: Database,
    repository: AffiliateCaptureHealthRepository,
) -> None:
    try:
        await refresh_idle_availability(
            cdp_url,
            tenant_id,
            shop_id,
            expected_platform_shop_id,
            database,
            repository,
        )
    except asyncio.CancelledError:
        raise
    except Exception as error:  # noqa: BLE001 -- next idle probe retries safely
        _log(
            "affiliate_idle_availability_failed",
            tenant_id=tenant_id,
            shop_id=shop_id,
            error_type=type(error).__name__,
        )


async def _configured_platform_shop_id(
    database: Database, tenant_id: UUID, shop_id: UUID
) -> str:
    async with database.system_session_factory() as session:
        platform_shop_id = await session.scalar(
            select(Shop.platform_shop_id).where(
                Shop.tenant_id == tenant_id,
                Shop.id == shop_id,
                Shop.platform == "tiktok",
                Shop.status == "active",
            )
        )
    if platform_shop_id is None:
        raise RuntimeError("Configured TikTok shop is not active or was not found.")
    return platform_shop_id
