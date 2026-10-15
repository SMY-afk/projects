from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

from arq import create_pool
from arq.connections import RedisSettings

from erp_api.core.config import get_settings


async def _run() -> list[dict[str, object]]:
    queue = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
    try:
        jobs = await queue.queued_jobs()
        result = []
        for job in jobs:
            if job.function != "sync_official_affiliate_job" or len(job.args) < 5:
                continue
            if job.args[2] != "creators":
                continue
            scheduled_at = (
                datetime.fromtimestamp(job.score / 1_000, UTC).isoformat()
                if job.score is not None
                else None
            )
            result.append(
                {
                    "jobId": job.job_id,
                    "shopId": job.args[1],
                    "windowStart": job.args[3],
                    "windowEnd": job.args[4],
                    "try": job.job_try,
                    "scheduledAt": scheduled_at,
                }
            )
        return result
    finally:
        await queue.aclose()


def main() -> None:
    print(json.dumps(asyncio.run(_run()), separators=(",", ":")))


if __name__ == "__main__":
    main()
