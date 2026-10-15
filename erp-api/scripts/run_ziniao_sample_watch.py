from __future__ import annotations

import argparse
import asyncio
import os
import platform
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from time import time

from backend.app.services.windows_background_process import background_process_options

if os.name == "nt":
    platform._wmi = None  # type: ignore[attr-defined]

from playwright.async_api import async_playwright
from sqlalchemy import select

from backend.app.services.capture_logging import capture_log
from backend.app.services.hubstudio_attached_browser import (
    connect_attached_hubstudio_browser,
)
from backend.app.services.hubstudio_cdp import read_cdp_platform_shop_ids
from backend.app.services.hubstudio_raw_sample_capture import (
    capture_review_batch_from_page,
)
from backend.app.services.hubstudio_sample_watch import _sample_page_matches
from backend.app.services.sample_pipeline_busy_retry import retry_shop_sync_busy
from backend.app.services.sample_raw_batch_store import SampleRawBatchStore
from backend.app.services.sample_watch_error_category import classify_watch_error
from backend.app.services.ziniao_sample_list_selenium import (
    activate_responsive_sample_page,
)
from erp_api.core.config import get_settings
from erp_api.infrastructure.database import Database
from erp_api.main import build_sample_application_services
from erp_api.models.shop import Shop
from erp_api.services.sample_application_time_enrichment import (
    SampleApplicationTimeEnrichmentService,
)
from erp_api.services.sample_shop_sync_lock import SampleShopSyncLock
from erp_api.services.ziniao_sample_feishu_sync import (
    sync_enriched_applications as _sync_enriched_applications,
)
from scripts.run_ziniao_creator_rolling import _ensure_browser

SHOP_NAME = "Akeleo Toys"

async def run(arguments: argparse.Namespace) -> str:
    settings = get_settings()
    database = Database(settings.database_url)
    try:
        shop = await _shop(database)
        session = await _ensure_browser(settings)
        debugging_port = await _resolve_cdp_port(
            session.debugging_port,
            shop.platform_shop_id,
        )
        activate_responsive_sample_page(
            debugging_port,
            shop.platform_shop_id,
        )
        cdp_url = f"http://127.0.0.1:{debugging_port}"
        services = build_sample_application_services(settings, database)
        feishu_sync = services["sample_feishu_sync_service"]
        if feishu_sync is None:
            raise RuntimeError("Feishu sample sync is not configured.")
        feishu = services["feishu_sample_client_router"].for_shop(shop.id)
        mappings = services["sample_feishu_mapping_repository"]
        shop_sync_lock = SampleShopSyncLock(database)
        async with async_playwright() as playwright:
            attached = await connect_attached_hubstudio_browser(playwright, cdp_url)
            if not attached.contexts:
                raise RuntimeError("Akeleo Toys browser has no available context.")
            disconnected = asyncio.Event()
            attached.on("disconnected", lambda *_: disconnected.set())
            result: dict[str, int] = {}
            raw_store = SampleRawBatchStore(Path(".runtime/sample-raw-queue"), str(shop.id))
            while not disconnected.is_set():
                result.clear()
                page = _sample_page(attached.contexts, shop.platform_shop_id)
                try:
                    capture = await capture_review_batch_from_page(
                        page,
                        shop.platform_shop_id,
                        raw_store,
                        timeout_seconds=arguments.capture_timeout_seconds,
                    )
                    applications = tuple(
                        application
                        for captured_page in capture.pages
                        for application in captured_page.applications
                    )
                    request_id = next(
                        (
                            captured_page.platform_request_id
                            for captured_page in capture.pages
                            if captured_page.platform_request_id
                        ),
                        None,
                    )
                    enriched = await SampleApplicationTimeEnrichmentService(database).enrich(
                        tenant_id=shop.tenant_id,
                        shop_id=shop.id,
                        applications=applications,
                        observed_at=datetime.now(UTC),
                        request_id=request_id,
                    )
                    feishu_result = (
                        {
                            "feishu_created": 0,
                            "feishu_updated": 0,
                            "feishu_deleted": 0,
                            "feishu_delete_pending": 0,
                            "feishu_deferred_reason": "manual_sequential_review",
                        }
                        if arguments.defer_feishu
                        else await retry_shop_sync_busy(
                            lambda enriched=enriched: _sync_enriched_applications(
                                feishu_sync,
                                tenant_id=shop.tenant_id,
                                shop_id=shop.id,
                                application_ids=enriched.application_ids,
                                obsolete_platform_application_ids=(
                                    enriched.obsolete_platform_application_ids
                                ),
                                grouped_product_updates=enriched.grouped_product_updates,
                                feishu=feishu,
                                mappings=mappings,
                                post_source_service=services["sample_shop_pipeline_service"],
                                shop_sync_lock=shop_sync_lock,
                            ),
                            retry_seconds=15,
                            max_wait_seconds=360,
                        )
                    )
                    result.update(
                        matched=enriched.matched_count,
                        updated=enriched.updated_count,
                        missing=enriched.missing_time_count,
                        pages_captured=len(capture.pages),
                        batch_sequence=capture.batch.sequence,
                        recovered_batch=capture.recovered,
                        **feishu_result,
                    )
                    if not any(
                        key in feishu_result
                        for key in ("feishu_error_type", "feishu_deferred_reason")
                    ):
                        await asyncio.to_thread(raw_store.acknowledge, capture.batch)
                        status = "succeeded"
                    else:
                        status = "processing_deferred"
                except TimeoutError:
                    status = "capture_timeout"
                capture_log(
                    "ziniao_sample_time_watch_cycle_completed",
                    tenant_id=shop.tenant_id,
                    shop_id=shop.id,
                    status=status,
                    **result,
                )
                if arguments.once:
                    return status
                remaining = _next_cycle_delay(
                    time(),
                    arguments.interval_seconds,
                    arguments.cycle_offset_seconds,
                )
                if remaining > 0:
                    await asyncio.sleep(remaining)
            return "cdp_disconnected"
    finally:
        await database.dispose()


def _sample_page(contexts, platform_shop_id: str):
    pages = [
        page
        for context in contexts
        for page in context.pages
        if _sample_page_matches(page.url, platform_shop_id)
    ]
    if not pages:
        raise RuntimeError("Akeleo Toys sample page is unavailable.")
    return pages[0]


async def _resolve_cdp_port(reported_port: int, platform_shop_id: str) -> int:
    candidates = dict.fromkeys((reported_port, *_ziniao_listening_ports()))
    matches = []
    for port in candidates:
        try:
            shop_ids = await read_cdp_platform_shop_ids(
                f"http://127.0.0.1:{port}"
            )
        except Exception:  # noqa: BLE001,S112 -- stale reported port is expected
            continue
        if shop_ids == frozenset({platform_shop_id}):
            matches.append(port)
    if len(matches) != 1:
        raise RuntimeError("Akeleo Toys Ziniao CDP port could not be resolved safely.")
    return matches[0]


def _ziniao_listening_ports() -> list[int]:
    if os.name != "nt":
        return []
    script = (
        "$ErrorActionPreference='SilentlyContinue'; "
        "Get-CimInstance Win32_Process -Filter \"Name='ziniaobrowser.exe'\" | "
        "ForEach-Object { if ($_.CommandLine -match "
        "'--remote-debugging-port(?:=|\\s+)(\\d+)') { $Matches[1] } }"
    )
    try:
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
            **background_process_options(),
        )
    except (OSError, subprocess.SubprocessError):
        return []
    return sorted(
        {
            int(match.group(0))
            for line in completed.stdout.splitlines()
            if (match := re.search(r"\d{1,5}", line)) is not None
            and 1 <= int(match.group(0)) <= 65_535
        }
    )


def _next_cycle_delay(
    timestamp: float, interval_seconds: float, offset_seconds: float
) -> float:
    phase = timestamp % interval_seconds
    delay = (offset_seconds - phase) % interval_seconds
    return interval_seconds if delay == 0 else delay


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
        description="Enrich Akeleo Toys sample times from Ziniao CDP."
    )
    parser.add_argument("--interval-seconds", type=float, default=300)
    parser.add_argument("--cycle-offset-seconds", type=float, default=90)
    parser.add_argument("--capture-timeout-seconds", type=float, default=120)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--defer-feishu", action="store_true")
    arguments = parser.parse_args()
    if (
        arguments.interval_seconds <= 0
        or arguments.capture_timeout_seconds <= 0
        or not 0 <= arguments.cycle_offset_seconds < arguments.interval_seconds
    ):
        parser.error("Intervals must be positive.")
    try:
        status = asyncio.run(run(arguments))
    except KeyboardInterrupt:
        return
    except Exception as error:
        category, code = classify_watch_error(error)
        capture_log(
            "ziniao_sample_watch_failed",
            error_type=type(error).__name__,
            error_category=category,
            error_code=code,
        )
        raise
    print(status)

if __name__ == "__main__":
    main()
