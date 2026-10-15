from __future__ import annotations

import asyncio
from uuid import UUID

from playwright.async_api import BrowserContext

from backend.app.services import tiktok_affiliate_intent_deferral as intent_deferral
from backend.app.services import tiktok_affiliate_intent_page as intent_page
from backend.app.services import tiktok_affiliate_intent_priority as intent_priority
from backend.app.services import tiktok_affiliate_intent_support as intent_support
from backend.app.services.capture_logging import capture_log as _log
from backend.app.services.tiktok_affiliate_analytics_capture import (
    TikTokAffiliateAnalyticsSynchronizer,
)
from backend.app.services.tiktok_affiliate_analytics_page_evidence import page_records
from backend.app.services.tiktok_affiliate_analytics_pager import (
    TikTokAffiliateAnalyticsPager,
)
from backend.app.services.tiktok_affiliate_analytics_run_state import CaptureGuardConfig
from backend.app.services.tiktok_affiliate_capture_dispatcher import (
    TikTokAffiliateCaptureDispatcher,
)
from backend.app.services.tiktok_affiliate_creator_capture_factory import (
    build_affiliate_creator_capture,
)
from backend.app.services.tiktok_affiliate_export_intent import run_export_intent
from backend.app.services.tiktok_affiliate_video_capture_factory import (
    build_affiliate_video_capture,
)
from backend.app.services.tiktok_affiliate_video_total_reconciliation import (
    verify_video_total_drift,
)
from erp_api.infrastructure.database import Database
from erp_api.services.affiliate_capture_health import AffiliateCaptureHealthRepository
from erp_api.services.affiliate_capture_intent_repository import (
    AffiliateCaptureIntentRepository,
)

_is_intent_target = intent_support.is_intent_target
_intent_timeout_seconds = intent_priority.intent_timeout_seconds


async def _run_next_intent(
    contexts: list[BrowserContext],
    tenant_id: UUID,
    database: Database,
    mutation_lock: asyncio.Lock,
    repository: AffiliateCaptureIntentRepository,
    stopped: asyncio.Event,
    health_repository: AffiliateCaptureHealthRepository | None = None,
    *,
    platform_shop_ids: frozenset[str],
    preempt_tasks: tuple[asyncio.Task[None], ...] = (),
) -> None:
    intent = await intent_priority.wait_for_intent(
        repository,
        tenant_id,
        stopped,
        platform_shop_ids=platform_shop_ids,
        preempt_tasks=preempt_tasks,
    )
    if intent is None:
        return
    try:
        prepared = await intent_page.prepare_intent_page(contexts, intent)
    except intent_page.IntentPageError as error:
        if await intent_deferral.defer_session_blocked_intent(
            error.category,
            tenant_id,
            intent,
            health_repository,
            page=error.page,
            stopped=stopped,
        ):
            return
        await repository.fail_intent(tenant_id, intent.run_id, error.category)
        _log(
            "affiliate_intent_failed",
            tenant_id=tenant_id,
            shop_id=intent.shop_id,
            run_id=intent.run_id,
            failure_category=error.category,
        )
        return
    if not await repository.claim_intent(tenant_id, intent.run_id):
        await prepared.cleanup()
        return
    creator_capture = build_affiliate_creator_capture(
        tenant_id,
        database,
        expected_query=prepared.query if intent.resource == "creators" else None,
        intent_job_id=intent.job_id if intent.resource == "creators" else None,
    )
    video_capture = build_affiliate_video_capture(
        tenant_id,
        database,
        expected_query=prepared.query if intent.resource == "videos" else None,
        intent_job_id=intent.job_id if intent.resource == "videos" else None,
    )
    _log(
        "affiliate_intent_claimed",
        tenant_id=tenant_id,
        shop_id=intent.shop_id,
        run_id=intent.run_id,
    )
    if await run_export_intent(
        prepared,
        creator_capture,
        video_capture,
        repository,
        tenant_id,
        intent,
        health_repository,
        stopped,
    ):
        return
    dispatcher = TikTokAffiliateCaptureDispatcher(creator_capture, video_capture)
    done = asyncio.Event()
    session_blocker: str | None = None
    video_context = None
    video_record_keys: set[str] = set()

    async def finalize(resource, snapshot) -> None:
        try:
            snapshot = await _reconciled_video_snapshot(
                prepared.page,
                prepared.query,
                resource,
                snapshot,
                video_context,
                frozenset(video_record_keys),
            )
            await _finalize_intent_resource(
                dispatcher,
                repository,
                tenant_id,
                intent,
                resource,
                snapshot,
            )
        finally:
            if resource == intent.resource:
                done.set()

    guard_config = CaptureGuardConfig(max_pages=500, max_run_seconds=1800)
    pager = TikTokAffiliateAnalyticsPager(
        mutation_lock,
        guard_config=guard_config,
        settle_delay_seconds=1.5,
        page_persister=dispatcher.persist_page,
        terminal_handler=finalize,
        page_requester=getattr(prepared.trigger, "request_page", None),
        page_number_provider=getattr(prepared.trigger, "current_page", None),
    )

    async def payload_handler(page, resource, payload, observation, context) -> None:
        nonlocal video_context
        if _is_intent_target(page, resource, prepared.page, intent.resource):
            if resource == "videos":
                video_record_keys.update(page_records(resource, payload)[1])
                video_context = context
            await pager.handle_payload(page, resource, payload, observation, context)

    async def failure_handler(page, resource, status, category) -> None:
        nonlocal session_blocker
        if not _is_intent_target(page, resource, prepared.page, intent.resource):
            return
        await pager.handle_failure(page, resource, status, category)
        failure_category = intent_support.intent_failure_category(category)
        session_blocker = await intent_deferral.persist_failure_or_deferral(
            repository, tenant_id, intent.run_id, failure_category
        )
        done.set()

    synchronizer = TikTokAffiliateAnalyticsSynchronizer(
        mutation_lock,
        payload_handler=payload_handler,
        failure_handler=failure_handler,
    )
    for context in contexts:
        context.on("response", synchronizer.schedule_response)
    try:
        await prepared.trigger()
        await intent_priority.wait_for_completion(
            done,
            stopped,
            timeout_seconds=_intent_timeout_seconds(intent.resource),
        )
        if not done.is_set():
            await repository.fail_intent(tenant_id, intent.run_id, "request_timeout")
    except Exception:  # noqa: BLE001 -- browser execution boundary
        category = await intent_deferral.page_session_blocker(prepared.page)
        session_blocker = await intent_deferral.persist_failure_or_deferral(
            repository, tenant_id, intent.run_id, category or "window_not_settable"
        )
    finally:
        await pager.stop()
        await synchronizer.wait_for_pending()
        await prepared.cleanup()
    if session_blocker:
        await intent_deferral.defer_session_blocked_intent(
            session_blocker,
            tenant_id,
            intent,
            health_repository,
            page=prepared.page,
            stopped=stopped,
        )


async def _reconciled_video_snapshot(
    page,
    query,
    resource: str,
    snapshot,
    response_context,
    record_keys: frozenset[str],
):
    result = dict(snapshot)
    if resource != "videos" or not await verify_video_total_drift(
        page,
        query,
        result,
        response_context,
        record_keys,
    ):
        return result
    result.update(
        status="complete",
        failure_category=None,
        terminal_reason="verified_source_total_drift",
    )
    _log(
        "affiliate_analytics_total_drift_confirmed",
        pages_fetched=result.get("pages_fetched"),
        records_unique=result.get("records_unique"),
        expected_total=result.get("expected_total"),
    )
    return result


async def _finalize_intent_resource(
    dispatcher,
    repository: AffiliateCaptureIntentRepository,
    tenant_id: UUID,
    intent,
    resource: str,
    snapshot,
) -> None:
    if resource != intent.resource:
        return
    await dispatcher.finalize_resource(resource, snapshot)
    if (
        snapshot.get("status") != "complete"
        and snapshot.get("failure_category") == "page_failed"
    ):
        await repository.fail_intent(
            tenant_id,
            intent.run_id,
            "request_timeout",
        )
