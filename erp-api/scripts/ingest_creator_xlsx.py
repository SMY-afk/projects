from __future__ import annotations

import argparse
import asyncio
import json
from datetime import date
from pathlib import Path
from uuid import uuid4

import httpx
from sqlalchemy import select

from app.parsers.xlsx_worksheet_reader import read_first_worksheet
from erp_api.core.config import get_settings
from erp_api.infrastructure.database import Database
from erp_api.models.shop import Shop
from erp_api.services.affiliate_center_contract import (
    AffiliateCenterQuery,
    AffiliateCenterResource,
)
from erp_api.services.affiliate_creator_file_ingest import (
    AffiliateCreatorFileIngestService,
)
from erp_api.services.affiliate_creator_persistence import AffiliateCreatorPersistence
from erp_api.services.analytics_sync_repository import AnalyticsSyncRepository
from erp_api.services.ziniao_creator_export import export_creator_xlsx
from erp_api.services.ziniao_webdriver_client import ZiniaoBrowserSession


def _arguments():
    parser = argparse.ArgumentParser(description="Ingest one official Creator XLSX.")
    parser.add_argument("--shop-name", required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--file", type=Path)
    source.add_argument("--ziniao-latest", action="store_true")
    source.add_argument("--ziniao-export", action="store_true")
    parser.add_argument("--from", dest="window_start", type=date.fromisoformat, required=True)
    parser.add_argument("--to", dest="window_end", type=date.fromisoformat, required=True)
    parser.add_argument("--source-row-count", type=int)
    return parser.parse_args()


async def _export_path(args, settings) -> Path:
    if args.file is not None:
        return args.file.resolve(strict=True)
    browser = await _running_browser(settings)
    download_path = Path(str(browser.get("downloadPath") or ""))
    if args.ziniao_export:
        driver_path = settings.ziniao_chromedriver_path
        if driver_path is None:
            raise RuntimeError("Ziniao ChromeDriver path is not configured.")
        session = ZiniaoBrowserSession(
            debugging_port=int(browser["debuggingPort"]),
            core_version=str(browser.get("core_version") or ""),
            core_type="Chromium",
            download_path=download_path,
            browser_path=Path(str(browser["browserPath"])),
        )
        return await asyncio.to_thread(
            export_creator_xlsx,
            session,
            driver_path,
            window_start=args.window_start,
            window_end=args.window_end,
        )
    return _latest_export(download_path, args.window_start, args.window_end)


async def _running_browser(settings) -> dict[str, object]:
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            settings.ziniao_webdriver_url,
            json={"action": "getRunningInfo", "requestId": str(uuid4())},
        )
        response.raise_for_status()
        payload = response.json()
    browsers = payload.get("browsers")
    if not isinstance(browsers, list) or len(browsers) != 1:
        raise RuntimeError("Exactly one Ziniao browser must be running.")
    browser = browsers[0]
    if not isinstance(browser, dict):
        raise TypeError("Ziniao running browser response is invalid.")
    return browser


def _latest_export(download_path: Path, window_start: date, window_end: date) -> Path:
    pattern = f"Creator_List_{window_start:%Y%m%d}-{window_end:%Y%m%d}_*.xlsx"
    files = sorted(
        download_path.glob(pattern),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    if not files:
        raise FileNotFoundError("Official Creator XLSX was not found.")
    return files[0]


def _source_row_count(content: bytes) -> int:
    rows = iter(read_first_worksheet(content))
    next(rows, None)
    return sum(
        1
        for row in rows
        if any(value is not None and str(value).strip() for value in row)
    )


async def _shop(database: Database, name: str) -> Shop:
    async with database.system_session_factory() as session:
        rows = (
            await session.execute(
                select(Shop).where(
                    Shop.shop_name == name,
                    Shop.platform == "tiktok",
                    Shop.status == "active",
                )
            )
        ).scalars().all()
    if len(rows) != 1:
        raise ValueError("Shop name must resolve to one active TikTok shop.")
    return rows[0]


async def _run(args):
    settings = get_settings()
    database = Database(settings.database_url)
    try:
        shop = await _shop(database, args.shop_name)
        export_path = await _export_path(args, settings)
        content = export_path.read_bytes()
        query = AffiliateCenterQuery(
            resource=AffiliateCenterResource.CREATORS,
            shop_id=shop.id,
            window_start=args.window_start,
            window_end=args.window_end,
            shop_timezone=shop.timezone,
            currency=(shop.currency or "USD").upper(),
            filters={},
        )
        service = AffiliateCreatorFileIngestService(
            AnalyticsSyncRepository.for_affiliate_center(database),
            AffiliateCreatorPersistence(database),
        )
        result = await service.ingest(
            shop.tenant_id,
            query,
            platform_shop_id=shop.platform_shop_id,
            job_id=f"ziniao-creator-xlsx:{shop.id}:{uuid4()}",
            file_name=export_path.name,
            content=content,
            source_row_count=args.source_row_count or _source_row_count(content),
        )
        return {
            "status": result.status,
            "shopId": str(shop.id),
            "runId": str(result.run_id),
            "reportId": str(result.report_id),
            "recordCount": result.record_count,
            "sourceRowCount": result.source_row_count,
            "unidentifiedRowCount": result.unidentified_row_count,
            "affiliateGmvMinor": result.affiliate_gmv_minor,
            "estimatedCommissionMinor": result.estimated_commission_minor,
            "orderCount": result.order_count,
            "itemsSold": result.items_sold,
        }
    finally:
        await database.dispose()


def main():
    try:
        result = asyncio.run(_run(_arguments()))
    except Exception as error:
        raise SystemExit(str(error)) from error
    print(json.dumps(result, separators=(",", ":")))


if __name__ == "__main__":
    main()
