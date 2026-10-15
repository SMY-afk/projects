"""Summarize the read-only five-shop daily creator sync gate."""

import asyncio
from datetime import UTC, datetime

from arq.connections import RedisSettings, create_pool

from erp_api.core.config import get_settings
from erp_api.infrastructure.database import Database
from erp_api.services.affiliate_schedule_queries import latest_due_schedule_date
from erp_api.workers.daily_valid_creator_jobs import _ready_snapshot
from scripts.daily_valid_creator_batch import evaluate_batch, load_batch_runs
from scripts.daily_valid_creator_report_gate import missing_creator_reports


async def main() -> None:
    settings = get_settings()
    database = Database(settings.database_url)
    redis = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    try:
        now = datetime.now(UTC)
        batch = latest_due_schedule_date(now)
        snapshot = await _ready_snapshot(
            {"database": database, "redis": redis}, now
        )
        print(f"BATCH={batch} ONLINE_READY={snapshot is not None}")
        if snapshot is None:
            return
        cutoffs = snapshot[0]
        missing = await missing_creator_reports(database, cutoffs)
        print(
            "CREATOR_REPORT_GAPS="
            + str({shop: len(windows) for shop, windows in missing.items()})
        )
        runs = await load_batch_runs(cutoffs, batch)
        try:
            result = evaluate_batch(cutoffs, batch, runs)
        except ValueError as error:
            print(f"BATCH_GATE=BLOCKED DETAILS={str(error)[:1200]}")
        else:
            print(
                "BATCH_GATE=READY "
                f"REQUIRED={result['required_windows']} "
                f"REUSED={result['reused_windows']}"
            )
    finally:
        await redis.aclose()
        await database.dispose()


if __name__ == "__main__":
    asyncio.run(main())
