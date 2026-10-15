from __future__ import annotations

import argparse
import asyncio
import os
import platform
import sys
from uuid import UUID

if os.name == "nt" and sys.version_info >= (3, 13):
    platform._wmi = None  # type: ignore[attr-defined]

from playwright.async_api import async_playwright

from backend.app.services.capture_logging import capture_log
from backend.app.services.deferred_sample_post_source import DeferredPostSourceService
from backend.app.services.hubstudio_sample_watch import (
    run_hubstudio_sample_watch,
)
from backend.app.services.sample_watch_error_category import (
    classify_watch_error,
    is_retryable_page_control_error,
)
from backend.app.services.tiktok_sample_creator_details_collector import (
    TikTokSampleCreatorDetailsCollector,
)
from erp_api.core.config import get_settings
from erp_api.infrastructure.database import Database
from erp_api.main import build_sample_application_services
from erp_api.services.hubstudio_sample_application_source import (
    HubStudioEnvironmentSnapshot,
    HubStudioSampleApplicationSource,
    HubStudioSampleTarget,
)
from erp_api.services.hubstudio_sample_ingest_service import (
    HubStudioSampleIngestService,
)
from erp_api.services.hubstudio_sample_profile_targets import (
    HubStudioSampleProfileTargetProvider,
)
from erp_api.services.sample_shop_sync_lock import SampleShopSyncLock

MAX_PLAYWRIGHT_CYCLES = 12


async def run(arguments: argparse.Namespace) -> str:
    if arguments.max_pages is not None and (
        not arguments.full or arguments.max_pages < 1
    ):
        raise ValueError("--max-pages requires --full and a positive value.")
    settings = get_settings()
    database = Database(settings.database_url)
    try:
        services = build_sample_application_services(settings, database)
        source_policy = services["sample_source_policy"]
        application_repository = services["sample_application_repository"]
        audit_repository = services["sample_sync_audit_repository"]
        feishu_sync_service = services["sample_feishu_sync_service"]
        post_source_service = services["sample_shop_pipeline_service"]
        if feishu_sync_service is None and not arguments.defer_feishu:
            raise RuntimeError("Feishu sample sync is not configured.")
        if arguments.defer_feishu:
            post_source_service = DeferredPostSourceService()

        target = HubStudioSampleTarget(
            tenant_id=arguments.tenant_id,
            shop_id=arguments.shop_id,
            environment_id=arguments.environment_id,
            platform_shop_id=arguments.platform_shop_id,
            cdp_url=arguments.cdp_url,
            official_access_state="missing_scope",
        )

        async def environment_probe(environment_id: str):
            if environment_id != target.environment_id:
                return None
            return HubStudioEnvironmentSnapshot(
                environment_id=target.environment_id,
                running=True,
                cdp_url=target.cdp_url,
            )

        source = HubStudioSampleApplicationSource(source_policy, environment_probe)
        preflight = await source.preflight(target)
        ingest = HubStudioSampleIngestService(
            audit_repository,
            application_repository,
            # The page is already constrained to the review queue and newest-first.
            # Read every review page so applications beyond page one are not skipped.
            latest_window=False,
            page_limit=arguments.max_pages,
        )
        profile_targets = HubStudioSampleProfileTargetProvider(
            database,
            activation_at=settings.feishu_sample_auto_assignment_activation_at,
            limit=arguments.profile_limit,
        )
        profile_collector = TikTokSampleCreatorDetailsCollector(
            target.tenant_id,
            target.shop_id,
            target.platform_shop_id,
            database,
        )
        while True:
            try:
                async with async_playwright() as playwright:
                    status = await run_hubstudio_sample_watch(
                        playwright=playwright,
                        source=source,
                        preflight=preflight,
                        ingest_service=ingest,
                        profile_target_provider=profile_targets,
                        profile_collector=profile_collector,
                        feishu_sync_service=feishu_sync_service,
                        post_source_service=post_source_service,
                        shop_sync_lock=SampleShopSyncLock(database),
                        interval_seconds=arguments.interval_seconds,
                        once=arguments.once,
                        max_cycles=None if arguments.once else MAX_PLAYWRIGHT_CYCLES,
                        capture_timeout_seconds=arguments.capture_timeout_seconds,
                        processing_timeout_seconds=arguments.processing_timeout_seconds,
                    )
            except Exception as error:
                if arguments.once or not is_retryable_page_control_error(error):
                    raise
                capture_log(
                    "hubstudio_sample_watch_retry_scheduled",
                    shop_id=arguments.shop_id,
                    reason=str(error),
                    retry_after_seconds=arguments.interval_seconds,
                )
                await asyncio.sleep(arguments.interval_seconds)
                continue
            if arguments.once or status != "recycle":
                return status
            capture_log(
                "hubstudio_sample_playwright_recycled",
                shop_id=arguments.shop_id,
                cycles=MAX_PLAYWRIGHT_CYCLES,
            )
    finally:
        await database.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Capture one shop's sample applications from HubStudio CDP."
    )
    parser.add_argument("--tenant-id", type=UUID, required=True)
    parser.add_argument("--shop-id", type=UUID, required=True)
    parser.add_argument("--environment-id", required=True)
    parser.add_argument("--platform-shop-id", required=True)
    parser.add_argument("--cdp-url", required=True)
    parser.add_argument("--interval-seconds", type=float, default=60)
    parser.add_argument("--capture-timeout-seconds", type=float, default=120)
    parser.add_argument("--processing-timeout-seconds", type=float, default=600)
    parser.add_argument("--profile-limit", type=int, default=20)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--defer-feishu", action="store_true")
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--max-pages", type=int)
    arguments = parser.parse_args()
    try:
        status = asyncio.run(run(arguments))
    except KeyboardInterrupt:
        return
    except Exception as error:
        category, code = classify_watch_error(error)
        capture_log(
            "hubstudio_sample_watch_failed",
            shop_id=arguments.shop_id,
            error_type=type(error).__name__,
            error_category=category,
            error_code=code,
        )
        raise
    print(status)


if __name__ == "__main__":
    main()
