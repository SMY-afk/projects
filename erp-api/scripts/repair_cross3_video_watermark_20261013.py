"""Fill one evidenced, missing video watermark; preserve history and statuses."""

import argparse
import asyncio
from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from arq.connections import RedisSettings, create_pool
from sqlalchemy import select

from erp_api.core.config import get_settings
from erp_api.infrastructure.database import Database
from erp_api.models.analytics_sync import AnalyticsRawPayload, AnalyticsSyncRun
from erp_api.services.affiliate_capture_health import AffiliateCaptureHealthRepository
from scripts.sample_watch_freshness import SHOPS, TENANT_ID

RUN_ID = UUID("896dfff4-a3cf-58e4-a01b-7ee78033c2fc")
CAPTURE_ID = "f1753198-8cd8-56ef-8947-85db7188b94c"
FILE_HASH = "0dab4f93957c9976828060ecdf49e814e3cf462494d387d563c64cc7f5f68c21"
LATEST_DAY = date(2026, 10, 9)
ZONE = ZoneInfo("America/Los_Angeles")


def validate_receipt(run, hashes, observed, now):
    if run is None or run.id != RUN_ID or run.shop_id != SHOPS["cross-border-3"]:
        raise ValueError("Exact successful receipt identity is missing")
    if run.tenant_id != TENANT_ID or not run.job_id.startswith(f"remote-export:{CAPTURE_ID}:"):
        raise ValueError("Original capture identity differs")
    if (run.resource_type, run.account_type, run.currency, run.status) != (
        "affiliate_video", "AFFILIATE_ACCOUNTS", "USD", "succeeded"
    ) or run.fetched_count != 1502 or run.persisted_count != 1502:
        raise ValueError("Original capture is not complete")
    start = run.window_start.astimezone(ZONE)
    end = run.window_end.astimezone(ZONE)
    if (start.date(), end.date(), start.time(), end.time()) != (
        date(2026, 10, 8), date(2026, 10, 10), time.min, time.min
    ) or hashes != [FILE_HASH]:
        raise ValueError("Original XLSX window or digest differs")
    if observed is None or observed[0] != LATEST_DAY or not (
        timedelta(0) <= now - observed[1] <= timedelta(hours=6)
    ):
        raise ValueError("Fresh direct TK date proof is missing")
    if run.latest_available_date not in (None, LATEST_DAY):
        raise ValueError("Existing nonempty watermark must not be overwritten")


async def main(apply):
    settings = get_settings()
    database = Database(settings.database_url)
    redis = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    try:
        observation = await AffiliateCaptureHealthRepository(redis).observed_evidence_for(
            TENANT_ID, SHOPS["cross-border-3"], "videos"
        )
        async with database.system_session_factory() as session:
            run = await session.scalar(select(AnalyticsSyncRun).where(
                AnalyticsSyncRun.id == RUN_ID, AnalyticsSyncRun.tenant_id == TENANT_ID
            ).with_for_update())
            payloads = (await session.scalars(select(AnalyticsRawPayload.payload).where(
                AnalyticsRawPayload.sync_run_id == RUN_ID,
                AnalyticsRawPayload.tenant_id == TENANT_ID,
                AnalyticsRawPayload.shop_id == SHOPS["cross-border-3"],
            ))).all()
            hashes = [(payload.get("export") or {}).get("fileSha256") for payload in payloads]
            validate_receipt(run, hashes, observation, datetime.now(UTC))
            print(f"WATERMARK_PREVIEW rows={int(run.latest_available_date is None)} old={run.latest_available_date} new={LATEST_DAY}")
            if not apply:
                await session.rollback()
                return
            run.latest_available_date = LATEST_DAY
            await session.commit()
        async with database.system_session_factory() as session:
            after = await session.scalar(select(AnalyticsSyncRun).where(
                AnalyticsSyncRun.id == RUN_ID, AnalyticsSyncRun.tenant_id == TENANT_ID
            ))
            validate_receipt(after, hashes, observation, datetime.now(UTC))
            if after.latest_available_date != LATEST_DAY:
                raise RuntimeError("Watermark readback differs")
            print("WATERMARK_READBACK_VERIFIED second_preview=0")
    finally:
        await redis.aclose()
        await database.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    asyncio.run(main(parser.parse_args().apply))
