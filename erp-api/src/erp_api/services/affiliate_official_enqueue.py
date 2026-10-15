from datetime import UTC, datetime
from uuid import UUID

from erp_api.services.affiliate_center_contract import (
    AffiliateCenterQuery,
    AffiliateCenterResource,
)
from erp_api.services.affiliate_daily_queries import (
    split_bounded_queries,
    split_compass_queries,
)

_REQUEST_DEDUP_SECONDS = 300


async def enqueue_official_queries(
    queue,
    sync_repository,
    tenant_id: UUID,
    queries: list[AffiliateCenterQuery],
) -> dict[str, object]:
    receipts = []
    request_slot = int(datetime.now(UTC).timestamp()) // _REQUEST_DEDUP_SECONDS
    for query in queries:
        chunks = (
            split_compass_queries(query)
            if query.resource is AffiliateCenterResource.CREATORS
            else split_bounded_queries(query, max_days=30)
        )
        for chunk in chunks:
            resource_type = (
                "affiliate_creator"
                if chunk.resource is AffiliateCenterResource.CREATORS
                else "affiliate_video"
            )
            job_id = (
                f"official-affiliate:{chunk.shop_id}:{chunk.resource.value}:"
                f"{chunk.window_start:%Y%m%d}:{chunk.window_end:%Y%m%d}:{request_slot}"
            )
            window_start, window_end = chunk.utc_window()
            run_id = await sync_repository.create_run(
                tenant_id,
                chunk.shop_id,
                resource_type=resource_type,
                window_start=window_start,
                window_end=window_end,
                start_cursor=None,
                job_id=job_id,
                currency=chunk.currency,
                account_type="AFFILIATE_ACCOUNTS",
                reuse_succeeded=True,
            )
            job = await queue.enqueue_job(
                "sync_official_affiliate_job",
                str(tenant_id),
                str(chunk.shop_id),
                chunk.resource.value,
                chunk.window_start.isoformat(),
                chunk.window_end.isoformat(),
                chunk.shop_timezone,
                chunk.currency,
                job_id,
                _job_id=job_id,
            )
            existing = job is None
            receipts.append(
                {
                    "runId": run_id,
                    "resource": chunk.resource.value,
                    "resourceType": resource_type,
                    "status": "queued",
                    "existing": existing,
                }
            )
    return {"items": receipts, "captureMode": "official_api_owned"}
