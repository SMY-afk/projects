from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from time import monotonic
from uuid import UUID

from playwright.async_api import Page

from backend.app.services.capture_logging import capture_log
from backend.app.services.tiktok_affiliate_analytics_page_control import (
    page_security_failure,
)
from erp_api.services.affiliate_capture_health import (
    AffiliateCaptureHealthRepository,
)
from erp_api.services.affiliate_capture_intent_repository import (
    AffiliateCaptureIntent,
    AffiliateCaptureIntentRepository,
)

_SESSION_BLOCKERS = frozenset({"captcha", "session_expired"})


@dataclass(frozen=True)
class CaptchaCooldownConfig:
    minimum_seconds: float = 120.0
    poll_seconds: float = 10.0
    stable_seconds: float = 20.0


def captcha_cooldown_config() -> CaptchaCooldownConfig:
    return CaptchaCooldownConfig(
        minimum_seconds=_seconds("AFFILIATE_CAPTCHA_COOLDOWN_SECONDS", 120.0),
        poll_seconds=_seconds("AFFILIATE_CAPTCHA_POLL_SECONDS", 10.0),
        stable_seconds=_seconds("AFFILIATE_CAPTCHA_STABLE_SECONDS", 20.0),
    )


def is_session_blocker(category: str) -> bool:
    return category in _SESSION_BLOCKERS


async def page_session_blocker(page: Page) -> str | None:
    security = await page_security_failure(page)
    if security is None or not is_session_blocker(security[1]):
        return None
    return security[1]


async def persist_failure_or_deferral(
    repository: AffiliateCaptureIntentRepository,
    tenant_id: UUID,
    run_id: UUID,
    category: str,
) -> str | None:
    if is_session_blocker(category):
        await repository.defer_intent(tenant_id, run_id)
        return category
    await repository.fail_intent(tenant_id, run_id, category)
    return None


async def defer_session_blocked_intent(
    category: str,
    tenant_id: UUID,
    intent: AffiliateCaptureIntent,
    health_repository: AffiliateCaptureHealthRepository | None,
    *,
    page: Page | None = None,
    stopped: asyncio.Event | None = None,
    cooldown_config: CaptchaCooldownConfig | None = None,
) -> bool:
    if category not in _SESSION_BLOCKERS:
        return False
    if health_repository is not None:
        await health_repository.record(tenant_id, intent.shop_id, category)
    capture_log(
        "affiliate_intent_deferred",
        tenant_id=tenant_id,
        shop_id=intent.shop_id,
        run_id=intent.run_id,
        failure_category=category,
    )
    if category == "captcha" and page is not None and stopped is not None:
        await _wait_for_manual_captcha_recovery(
            page,
            stopped,
            cooldown_config or captcha_cooldown_config(),
            tenant_id,
            intent,
        )
    return True


async def _wait_for_manual_captcha_recovery(
    page: Page,
    stopped: asyncio.Event,
    config: CaptchaCooldownConfig,
    tenant_id: UUID,
    intent: AffiliateCaptureIntent,
) -> None:
    started = monotonic()
    clean_since: float | None = None
    capture_log(
        "affiliate_captcha_cooldown_started",
        tenant_id=tenant_id,
        shop_id=intent.shop_id,
        run_id=intent.run_id,
        cooldown_seconds=config.minimum_seconds,
    )
    while not stopped.is_set():
        now = monotonic()
        security = await page_security_failure(page)
        if security is None:
            clean_since = clean_since or now
        else:
            clean_since = None
        cooled = now - started >= config.minimum_seconds
        stable = clean_since is not None and now - clean_since >= config.stable_seconds
        if cooled and stable:
            capture_log(
                "affiliate_captcha_cooldown_completed",
                tenant_id=tenant_id,
                shop_id=intent.shop_id,
                run_id=intent.run_id,
            )
            return
        try:
            await asyncio.wait_for(stopped.wait(), timeout=config.poll_seconds)
        except TimeoutError:
            continue


def _seconds(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError:
        return default
    return value if value > 0 else default
