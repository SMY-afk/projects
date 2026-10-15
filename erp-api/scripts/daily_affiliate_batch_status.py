"""Read the persisted per-shop creator/video/live task list for one batch."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select

from erp_api.core.config import get_settings
from erp_api.infrastructure.database import Database
from erp_api.models.analytics_sync import AnalyticsSyncRun
from erp_api.models.shop import Shop
from erp_api.services.affiliate_local_export_service import TARGET_SHOPS
from erp_api.services.affiliate_schedule_queries import latest_due_schedule_date

SOURCE_NAMES = {target.source_name: target.business_name for target in TARGET_SHOPS}


def task_row(run: AnalyticsSyncRun, source_name: str, timezone: str) -> dict:
    parts = run.job_id.split(":")
    if len(parts) == 8 and parts[0] == "affiliate-schedule":
        cutoff, resource, window = parts[2], parts[4], parts[5]
        claimed_shop = parts[3]
    elif len(parts) == 6 and parts[:2] == ["affiliate", "live-batch"]:
        cutoff, resource, window = parts[4], "live", parts[5]
        claimed_shop = parts[3]
    else:
        raise ValueError("Invalid scheduled capture task identity")
    zone = ZoneInfo(timezone)
    start = run.window_start.astimezone(zone).date()
    end = run.window_end.astimezone(zone).date() - timedelta(days=1)
    if claimed_shop != str(run.shop_id) or window != f"{start:%Y%m%d}-{end:%Y%m%d}":
        raise ValueError("Scheduled capture task window identity mismatch")
    return {
        "shop": SOURCE_NAMES[source_name],
        "resource": resource,
        "cutoff": date.fromisoformat(cutoff).isoformat(),
        "window": [start.isoformat(), end.isoformat()],
        "runId": str(run.id),
        "status": run.status,
        "fetchedCount": run.fetched_count,
        "persistedCount": run.persisted_count,
    }


async def batch_status(batch_date: date) -> dict:
    settings = get_settings()
    tenant_id = settings.affiliate_export_tenant_id
    if tenant_id is None:
        raise RuntimeError("Affiliate export tenant is not configured")
    database = Database(settings.database_url)
    try:
        async with database.system_session_factory() as session:
            rows = (
                await session.execute(
                    select(AnalyticsSyncRun, Shop.shop_name, Shop.timezone)
                    .join(
                        Shop,
                        (Shop.id == AnalyticsSyncRun.shop_id)
                        & (Shop.tenant_id == AnalyticsSyncRun.tenant_id),
                    )
                    .where(
                        AnalyticsSyncRun.tenant_id == tenant_id,
                        or_(
                            AnalyticsSyncRun.job_id.like(
                                f"affiliate-schedule:{batch_date:%Y%m%d}:%"
                            ),
                            AnalyticsSyncRun.job_id.like(
                                f"affiliate:live-batch:{batch_date:%Y%m%d}:%"
                            ),
                        ),
                    )
                    .order_by(Shop.shop_name, AnalyticsSyncRun.started_at)
                )
            ).all()
    finally:
        await database.dispose()
    tasks = [
        task_row(run, name, timezone)
        for run, name, timezone in rows
        if name in SOURCE_NAMES and timezone
    ]
    return {
        "batchDate": batch_date.isoformat(),
        "taskCount": len(tasks),
        "tasks": tasks,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-date", type=date.fromisoformat)
    args = parser.parse_args()
    selected = args.batch_date or latest_due_schedule_date(datetime.now(UTC))
    print(json.dumps(asyncio.run(batch_status(selected)), ensure_ascii=False))


if __name__ == "__main__":
    main()
