from __future__ import annotations

import argparse
import asyncio
import json
from datetime import date, timedelta
from uuid import uuid4

from arq import create_pool
from arq.connections import RedisSettings
from arq.constants import default_queue_name, job_key_prefix
from sqlalchemy import select

from erp_api.core.config import get_settings
from erp_api.infrastructure.database import Database
from erp_api.models.shop import Shop

WINDOWS = (
    (date(2026, 8, 25), date(2026, 8, 31), "recent_7_days"),
    (date(2026, 8, 2), date(2026, 8, 31), "recent_30_days"),
    (date(2026, 7, 1), date(2026, 7, 30), "fixed_60_days_part_1"),
    (date(2026, 7, 31), date(2026, 8, 29), "fixed_60_days_part_2"),
)


def _arguments():
    parser = argparse.ArgumentParser(description="Queue Akeleo creator XLSX windows.")
    parser.add_argument("--shop-name", required=True)
    parser.add_argument(
        "--only",
        choices=[label for _, _, label in WINDOWS],
        help="Queue only one named window.",
    )
    parser.add_argument("--first-delay-minutes", type=int, default=60)
    parser.add_argument("--spacing-minutes", type=int, default=60)
    parser.add_argument(
        "--replace-pending",
        action="store_true",
        help="Remove pending Compass creator windows for this shop first.",
    )
    return parser.parse_args()


async def _run(args):
    settings = get_settings()
    database = Database(settings.database_url)
    queue = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    try:
        async with database.system_session_factory() as session:
            shops = (
                await session.execute(
                    select(Shop).where(
                        Shop.shop_name == args.shop_name,
                        Shop.platform == "tiktok",
                        Shop.status == "active",
                    )
                )
            ).scalars().all()
        if len(shops) != 1:
            raise ValueError("Shop name must resolve to one active TikTok shop.")
        shop = shops[0]
        removed = (
            await _remove_pending_windows(queue, str(shop.id))
            if args.replace_pending
            else 0
        )
        queued = []
        windows = [window for window in WINDOWS if not args.only or window[2] == args.only]
        for index, (start, end, label) in enumerate(windows):
            delay_minutes = args.first_delay_minutes + index * args.spacing_minutes
            job_id = f"compass-window:{shop.id}:{label}:{uuid4().hex[:8]}"
            job = await queue.enqueue_job(
                "sync_official_affiliate_job",
                str(shop.tenant_id),
                str(shop.id),
                "creators",
                start.isoformat(),
                end.isoformat(),
                shop.timezone,
                (shop.currency or "USD").upper(),
                job_id,
                _job_id=job_id,
                _defer_by=timedelta(minutes=delay_minutes),
            )
            if job is None:
                raise RuntimeError(f"Could not queue {label}.")
            queued.append({"window": label, "delayMinutes": delay_minutes})
        return {"status": "queued", "removed": removed, "items": queued}
    finally:
        await queue.aclose()
        await database.dispose()


async def _remove_pending_windows(queue, shop_id: str) -> int:
    matches = [
        job
        for job in await queue.queued_jobs()
        if job.function == "sync_official_affiliate_job"
        and len(job.args) >= 3
        and str(job.args[1]) == shop_id
        and job.args[2] == "creators"
        and str(job.job_id or "").startswith(f"compass-window:{shop_id}:")
    ]
    if not matches:
        return 0
    async with queue.pipeline(transaction=True) as transaction:
        for job in matches:
            transaction.zrem(default_queue_name, job.job_id)
            transaction.delete(job_key_prefix + str(job.job_id))
        await transaction.execute()
    return len(matches)


def main():
    try:
        result = asyncio.run(_run(_arguments()))
    except Exception as error:
        raise SystemExit(str(error)) from error
    print(json.dumps(result, separators=(",", ":")))


if __name__ == "__main__":
    main()
