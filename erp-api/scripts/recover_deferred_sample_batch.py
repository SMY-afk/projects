"""Queue one verified remote sample batch for the existing ECS sample worker."""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime, timedelta

from arq.connections import RedisSettings, create_pool
from arq.jobs import Job
from sqlalchemy import select

from erp_api.core.config import get_settings
from erp_api.infrastructure.database import Database
from erp_api.models.sample_ingest_batch import SampleIngestBatch
from erp_api.services.sample_business_readiness import (
    SAMPLE_SOURCE_STALE_SECONDS,
    SampleBusinessReadiness,
)
from erp_api.workers.sample_queue import SAMPLE_QUEUE_NAME
from scripts.sample_watch_freshness import SHOPS, TENANT_ID

REMOTE_SHOPS = frozenset(SHOPS) - {"local"}


async def enqueue_verified_batch(redis, shop_label, batch_id) -> str:
    arguments = (
        "process_remote_sample_batch_job", str(TENANT_ID),
        str(SHOPS[shop_label]), str(batch_id),
    )
    job_id = f"remote-sample:{batch_id}"
    job = await redis.enqueue_job(*arguments, _queue_name=SAMPLE_QUEUE_NAME, _job_id=job_id)
    if job is not None:
        return "QUEUED"
    prior = await Job(job_id, redis, _queue_name=SAMPLE_QUEUE_NAME).result_info()
    if prior is None or prior.success:
        return "ALREADY_QUEUED_OR_COMPLETE"
    job = await redis.enqueue_job(
        *arguments, _queue_name=SAMPLE_QUEUE_NAME, _job_id=job_id + ":recovery",
    )
    return "RECOVERY_QUEUED" if job is not None else "RECOVERY_ALREADY_QUEUED_OR_COMPLETE"


async def run(shop_label: str, enqueue: bool) -> None:
    settings = get_settings()
    database = Database(settings.database_url)
    try:
        async with database.system_session_factory() as session:
            batch = await session.scalar(
                select(SampleIngestBatch)
                .where(
                    SampleIngestBatch.tenant_id == TENANT_ID,
                    SampleIngestBatch.shop_id == SHOPS[shop_label],
                    SampleIngestBatch.source_type == "hubstudio_cdp",
                    SampleIngestBatch.source_identity.like("remote:%"),
                    SampleIngestBatch.status == "complete",
                    SampleIngestBatch.finished_at.is_not(None),
                )
                .order_by(SampleIngestBatch.finished_at.desc())
                .limit(1)
            )
        if batch is None:
            raise RuntimeError("No complete remote sample batch was found")
        if batch.expected_total is not None and batch.expected_total != batch.captured_total:
            raise RuntimeError("Latest remote sample batch is incomplete")
        if datetime.now(UTC) - batch.finished_at > timedelta(seconds=SAMPLE_SOURCE_STALE_SECONDS):
            raise RuntimeError("Latest remote sample batch is stale")
        evidence = batch.completeness_evidence or {}
        if not evidence.get("application_ids"):
            raise RuntimeError("Remote sample batch has no application IDs")
        print(
            f"SHOP={shop_label} BATCH={batch.id} FINISHED={batch.finished_at.isoformat()} "
            f"ROWS={batch.captured_total} APPLICATION_IDS={len(evidence['application_ids'])}"
        )
        if not enqueue:
            print("DRY_RUN_ONLY")
            return
        await SampleBusinessReadiness().require_ready(tenant_id=TENANT_ID, shop_id=SHOPS[shop_label])
        redis = await create_pool(RedisSettings.from_dsn(settings.redis_url))
        try:
            queue_state = await enqueue_verified_batch(redis, shop_label, batch.id)
        finally:
            await redis.aclose()
        print(queue_state)
    finally:
        await database.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shop", required=True, choices=sorted(REMOTE_SHOPS))
    parser.add_argument("--enqueue", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(args.shop, args.enqueue))


if __name__ == "__main__":
    main()
