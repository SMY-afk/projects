from __future__ import annotations

import asyncio
import os
from uuid import UUID

from playwright.async_api import async_playwright
from sqlalchemy import select

from backend.app.services import hubstudio_attached_browser as attached_browser
from backend.app.services import tiktok_affiliate_intent_page as intent_page
from backend.app.services import tiktok_affiliate_intent_priority as intent_priority
from backend.app.services import tiktok_affiliate_intent_runner as intent_runner
from backend.app.services import tiktok_affiliate_page_hygiene as page_hygiene
from backend.app.services.affiliate_capture_availability_startup import (
    restore_capture_available_dates,
)
from backend.app.services.affiliate_capture_health_monitor import (
    run_capture_availability_refresh,
    run_capture_health_heartbeat,
    run_connecting_health_heartbeat,
)
from backend.app.services.capture_logging import capture_log as _log
from backend.app.services.tiktok_affiliate_capture_options import (
    capture_batch_size as _capture_batch_size,
)
from backend.app.services.tiktok_affiliate_capture_options import (
    capture_preflight_timeout_seconds as _capture_preflight_timeout_seconds,
)
from backend.app.services.tiktok_affiliate_creator_detail_backfill_factory import (
    build_creator_detail_backfill,
)
from backend.app.services.tiktok_affiliate_creator_detail_capture import (
    TikTokAffiliateCreatorDetailCapture,
)
from backend.app.services.tiktok_affiliate_creator_summary_capture import (
    TikTokAffiliateCreatorSummaryCapture,
)
from backend.app.services.tiktok_seller_capture import TikTokSellerCenterSynchronizer
from backend.app.services.tiktok_seller_export_sync import (
    TikTokSellerExportSynchronizer,
)
from erp_api.infrastructure.database import Database
from erp_api.models.shop import Shop
from erp_api.services.affiliate_capture_health import (
    AffiliateCaptureHealthRepository,
)
from erp_api.services.affiliate_capture_intent_repository import (
    AffiliateCaptureIntentRepository,
)
from erp_api.services.affiliate_sync_repository import AffiliateSyncRepository
from erp_api.services.scraped_data_repository import ScrapedDataRepository
from erp_api.services.seller_evidence_sync_repository import (
    SellerEvidenceSyncRepository,
)

_detail_backfill_enabled = intent_priority.detail_backfill_enabled
_is_intent_target = intent_runner._is_intent_target
_run_next_intent = intent_runner._run_next_intent


async def run_capture_session(
    cdp_url: str,
    tenant_id: UUID,
    shop_id: UUID,
    database: Database,
    *,
    health_repository: AffiliateCaptureHealthRepository | None = None,
) -> bool:
    mutation_lock = asyncio.Lock()
    seller_repository = SellerEvidenceSyncRepository(database)
    intent_repository = AffiliateCaptureIntentRepository(database)
    creator_detail_capture = TikTokAffiliateCreatorDetailCapture(
        tenant_id, database, mutation_lock
    )
    creator_summary_capture = TikTokAffiliateCreatorSummaryCapture(
        tenant_id, database, mutation_lock
    )
    from backend.app.services.tiktok_affiliate_capture import (
        TikTokAffiliateOrderSynchronizer,
    )

    order_syncer = TikTokAffiliateOrderSynchronizer(
        raw_repository=ScrapedDataRepository(database),
        sync_repository=AffiliateSyncRepository(database),
        tenant_id=tenant_id,
        mutation_lock=mutation_lock,
    )
    seller_syncer = TikTokSellerCenterSynchronizer(
        raw_repository=ScrapedDataRepository(database),
        sync_repository=seller_repository,
        tenant_id=tenant_id,
        mutation_lock=mutation_lock,
        enable_product_fallback=os.getenv("HUBSTUDIO_PRODUCT_FALLBACK") == "1",
    )
    setup_stopped = asyncio.Event()
    collector_pages = []
    connecting_health_task: asyncio.Task[None] | None = None
    if health_repository is not None:
        connecting_health_task = asyncio.create_task(
            run_connecting_health_heartbeat(
                tenant_id,
                shop_id,
                health_repository,
                setup_stopped,
            )
        )
    async with async_playwright() as playwright:
        try:
            browser = await attached_browser.connect_attached_hubstudio_browser(
                playwright,
                cdp_url,
            )
            if not browser.contexts:
                raise RuntimeError("Hubstudio browser has no available context.")
            async with asyncio.timeout(_capture_preflight_timeout_seconds()):
                await page_hygiene.close_excess_managed_pages(
                    page
                    for context in browser.contexts
                    for page in tuple(context.pages)
                )
                for context in browser.contexts:
                    await context.route(
                        "**/easesafe/oec_trade_order_export/object/**",
                        seller_syncer.handle_export_route,
                    )
                    context.on("response", order_syncer.schedule_response)
                    context.on("response", seller_syncer.schedule_response)
                    context.on("response", creator_detail_capture.schedule_response)
                    context.on("response", creator_summary_capture.schedule_response)
                collector_pages = await page_hygiene.ensure_affiliate_resource_pages(
                    browser.contexts
                )
                platform_shop_ids = intent_page.browser_platform_shop_ids(
                    page for context in browser.contexts for page in context.pages
                )
                await _require_expected_shop(
                    database, tenant_id, shop_id, platform_shop_ids
                )
        except Exception:
            await page_hygiene.close_collector_pages(collector_pages)
            raise
        finally:
            setup_stopped.set()
            if connecting_health_task is not None:
                await asyncio.gather(
                    connecting_health_task,
                    return_exceptions=True,
                )
        stopped = asyncio.Event()
        browser.on("disconnected", lambda *_: stopped.set())
        health_task: asyncio.Task[None] | None = None
        availability_task: asyncio.Task[None] | None = None
        if health_repository is not None:
            health_task = asyncio.create_task(
                run_capture_health_heartbeat(
                    browser.contexts,
                    tenant_id,
                    shop_id,
                    health_repository,
                    stopped,
                )
            )
            latest_available_dates = await restore_capture_available_dates(
                database,
                health_repository,
                browser.contexts,
                tenant_id,
                shop_id,
            )
            await health_repository.record(
                tenant_id,
                shop_id,
                "online",
                latest_available_date=(
                    min(latest_available_dates.values())
                    if latest_available_dates
                    else None
                ),
                latest_available_dates=latest_available_dates,
            )
            availability_task = asyncio.create_task(
                run_capture_availability_refresh(
                    browser.contexts,
                    tenant_id,
                    shop_id,
                    health_repository,
                    stopped,
                    mutation_lock,
                    interval_seconds=float(
                        os.getenv("AFFILIATE_AVAILABILITY_REFRESH_SECONDS", "300")
                    ),
                )
            )
        seller_exporter = TikTokSellerExportSynchronizer(
            browser.contexts,
            seller_repository,
            tenant_id,
            mutation_lock,
            interval_seconds=float(os.getenv("SELLER_EXPORT_INTERVAL_SECONDS", "1800")),
            lookback_days=int(os.getenv("SELLER_EXPORT_LOOKBACK_DAYS", "28")),
        )
        seller_task = asyncio.create_task(seller_exporter.run(stopped))
        creator_detail_capture.start_open_pages(
            [page for context in browser.contexts for page in context.pages]
        )
        detail_backfill_task: asyncio.Task[None] | None = None
        if _detail_backfill_enabled():
            detail_backfill = build_creator_detail_backfill(
                tenant_id, database, creator_detail_capture
            )
            detail_backfill_task = asyncio.create_task(
                detail_backfill.run(browser.contexts, stopped)
            )
        _log(
            "affiliate_syncer_connected",
            tenant_id=tenant_id,
            shop_id=shop_id,
            context_count=len(browser.contexts),
            page_count=sum(len(context.pages) for context in browser.contexts),
        )
        try:
            for batch_index in range(_capture_batch_size()):
                await _run_next_intent(
                    browser.contexts,
                    tenant_id,
                    database,
                    mutation_lock,
                    intent_repository,
                    stopped,
                    health_repository,
                    platform_shop_ids=platform_shop_ids,
                    preempt_tasks=tuple(
                        task
                        for task in (
                            detail_backfill_task,
                            availability_task,
                        )
                        if task is not None
                    ),
                )
                if stopped.is_set() or batch_index + 1 >= _capture_batch_size():
                    break
                if (
                    await intent_repository.next_queued(tenant_id, platform_shop_ids)
                    is None
                ):
                    break
            if health_repository is not None and not stopped.is_set():
                await _refresh_completed_capture_dates(
                    database,
                    health_repository,
                    browser.contexts,
                    tenant_id,
                    shop_id,
                )
        finally:
            seller_task.cancel()
            pending_tasks = [seller_task]
            if health_task is not None:
                health_task.cancel()
                pending_tasks.append(health_task)
            if availability_task is not None:
                availability_task.cancel()
                pending_tasks.append(availability_task)
            if detail_backfill_task is not None:
                detail_backfill_task.cancel()
                pending_tasks.append(detail_backfill_task)
            await asyncio.gather(*pending_tasks, return_exceptions=True)
            await creator_detail_capture.stop()
            await creator_summary_capture.stop()
            await order_syncer.wait_for_pending()
            await seller_syncer.wait_for_pending()
            await page_hygiene.close_collector_pages(collector_pages)
            _log(
                "affiliate_syncer_disconnected",
                tenant_id=tenant_id,
                shop_id=shop_id,
            )
        return stopped.is_set()


async def _refresh_completed_capture_dates(
    database: Database,
    health_repository: AffiliateCaptureHealthRepository,
    contexts,
    tenant_id: UUID,
    shop_id: UUID,
) -> None:
    try:
        latest_dates = await restore_capture_available_dates(
            database,
            health_repository,
            contexts,
            tenant_id,
            shop_id,
        )
        await health_repository.record(
            tenant_id,
            shop_id,
            "online",
            latest_available_date=(min(latest_dates.values()) if latest_dates else None),
            latest_available_dates=latest_dates,
        )
    except Exception:  # noqa: BLE001 -- completed capture must stay committed
        _log(
            "affiliate_completed_dates_refresh_failed",
            tenant_id=tenant_id,
            shop_id=shop_id,
        )


async def _require_expected_shop(
    database: Database,
    tenant_id: UUID,
    shop_id: UUID,
    browser_platform_shop_ids: frozenset[str],
) -> None:
    async with database.system_session_factory() as session:
        expected_platform_shop_id = await session.scalar(
            select(Shop.platform_shop_id).where(
                Shop.tenant_id == tenant_id,
                Shop.id == shop_id,
                Shop.platform == "tiktok",
                Shop.status == "active",
            )
        )
    if expected_platform_shop_id is None:
        raise RuntimeError("Configured TikTok shop is not active or was not found.")
    if expected_platform_shop_id not in browser_platform_shop_ids:
        raise RuntimeError("HubStudio browser does not contain the configured shop.")
