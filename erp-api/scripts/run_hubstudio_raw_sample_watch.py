"""Single-shop latest-window sample watcher using verified raw CDP capture."""

from __future__ import annotations

import argparse
import asyncio
import os
import platform
import sys
from pathlib import Path
from time import monotonic
from uuid import UUID

if os.name == "nt" and sys.version_info >= (3, 13):
    platform._wmi = None  # type: ignore[attr-defined]

from backend.app.services.capture_logging import capture_log
from backend.app.services.sample_raw_batch_store import SampleRawBatchStore
from backend.app.services.sample_raw_capture_retry import (
    capture_review_batch_with_retry,
)
from backend.app.services.sample_watch_error_category import (
    classify_watch_error,
    requires_cdp_rediscovery,
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
from erp_api.services.hubstudio_sample_types import HubStudioSampleCapture
from erp_api.services.sample_raw_capture_lock import SampleRawCaptureLock
from erp_api.services.sample_shop_sync_lock import SampleShopSyncLock


async def run(arguments: argparse.Namespace) -> None:
    if arguments.interval_seconds <= 0:
        raise ValueError("Sample watcher interval must be positive")
    settings = get_settings()
    database = Database(settings.database_url)
    try:
        services = build_sample_application_services(settings, database)
        pipeline = services["sample_shop_pipeline_service"]
        if pipeline is None or services["sample_feishu_sync_service"] is None:
            raise RuntimeError("Sample Feishu pipeline is not configured")
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

        source = HubStudioSampleApplicationSource(
            services["sample_source_policy"], environment_probe
        )
        preflight = await source.preflight(target)
        ingest = HubStudioSampleIngestService(
            services["sample_sync_audit_repository"],
            services["sample_application_repository"],
            latest_window=False,
        )
        shop_lock = SampleShopSyncLock(database)
        capture_lock = SampleRawCaptureLock(database)
        raw_store = SampleRawBatchStore(
            Path(".runtime/sample-raw-queue"), str(target.shop_id)
        )
        while True:
            started = monotonic()
            status = "failed"
            records = 0
            pages_captured = 0
            processing_status = None
            batch_sequence = None
            recovered_batch = False
            recycle_required = False
            try:
                async with capture_lock.acquire(
                    target.tenant_id, target.shop_id
                ) as capture_acquired:
                    if not capture_acquired:
                        status = "succeeded"
                        processing_status = "duplicate_capture_prevented"
                    else:
                        await source.revalidate(preflight)
                        capture = await capture_review_batch_with_retry(
                            preflight.normalized_cdp_url,
                            target.platform_shop_id,
                            raw_store,
                            timeout_seconds=arguments.capture_timeout_seconds,
                        )
                        pages = capture.pages
                        batch_sequence = capture.batch.sequence
                        recovered_batch = capture.recovered
                        pages_captured = len(pages)
                        records = sum(len(page.applications) for page in pages)
                        source_results = []
                        stored_pages = raw_store.load_pages(capture.batch)
                        for page, stored_page in zip(pages, stored_pages, strict=True):
                            result = await ingest.ingest_page(
                                HubStudioSampleCapture(
                                    target=target,
                                    page=page,
                                    observed_at=stored_page.response_observed_at,
                                )
                            )
                            source_results.append(result)
                            status = result.status
                            if status not in {"running", "succeeded"}:
                                break
                        if status == "running":
                            status = "pagination_incomplete"
                        if status == "succeeded":
                            await asyncio.to_thread(
                                raw_store.acknowledge, capture.batch
                            )
                            async with shop_lock.acquire(
                                target.tenant_id, target.shop_id
                            ) as acquired:
                                if acquired:
                                    completed = await asyncio.wait_for(
                                        pipeline.complete_after_source(
                                            tenant_id=target.tenant_id,
                                            shop_id=target.shop_id,
                                            source_type="hubstudio_cdp",
                                            source_results=tuple(source_results),
                                        ),
                                        timeout=arguments.processing_timeout_seconds,
                                    )
                                    processing_status = completed.status
                                else:
                                    processing_status = "shop_sync_busy"
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001 -- leave the shop to retry
                if status == "succeeded":
                    status = "processing_failed"
                category, code = classify_watch_error(error)
                capture_log(
                    "hubstudio_raw_sample_watch_failed",
                    shop_id=target.shop_id,
                    error_type=type(error).__name__,
                    error_category=category,
                    error_code=code,
                )
                processing_status = type(error).__name__
                recycle_required = requires_cdp_rediscovery(error)
            capture_log(
                "hubstudio_sample_watch_cycle_completed",
                shop_id=target.shop_id,
                status=status,
                source_records=records,
                pages_captured=pages_captured,
                batch_sequence=batch_sequence,
                recovered_batch=recovered_batch,
                processing_status=processing_status,
                capture_method="raw_cdp_persistent_queue",
            )
            if recycle_required and not arguments.once:
                raise RuntimeError("Raw sample watcher requires CDP rediscovery")
            if arguments.once:
                if status != "succeeded" or processing_status in {
                    "shop_sync_busy", "RuntimeError", "TimeoutError"
                }:
                    raise RuntimeError("Raw sample watch cycle did not complete")
                return
            remaining = arguments.interval_seconds - (monotonic() - started)
            if remaining > 0:
                await asyncio.sleep(remaining)
    finally:
        await database.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tenant-id", type=UUID, required=True)
    parser.add_argument("--shop-id", type=UUID, required=True)
    parser.add_argument("--environment-id", required=True)
    parser.add_argument("--platform-shop-id", required=True)
    parser.add_argument("--cdp-url", required=True)
    parser.add_argument("--interval-seconds", type=float, default=60)
    parser.add_argument("--capture-timeout-seconds", type=float, default=240)
    parser.add_argument("--processing-timeout-seconds", type=float, default=1800)
    parser.add_argument("--once", action="store_true")
    arguments = parser.parse_args()
    if (
        arguments.interval_seconds <= 0
        or arguments.capture_timeout_seconds <= 0
        or arguments.processing_timeout_seconds <= 0
    ):
        parser.error("Intervals must be positive")
    asyncio.run(run(arguments))


if __name__ == "__main__":
    main()
