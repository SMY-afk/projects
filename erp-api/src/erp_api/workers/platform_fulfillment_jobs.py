from __future__ import annotations

from uuid import UUID

from arq import Retry


def platform_fulfillment_job_id(event_id: str, attempt_count: int) -> str:
    return f"platform-fulfillment:{event_id}:{attempt_count}"


async def enqueue_platform_fulfillment(
    redis, tenant_id: str, event_id: str, *, attempt_count: int = 0
) -> bool:
    await redis.enqueue_job(
        "process_platform_fulfillment_job",
        tenant_id,
        event_id,
        _job_id=platform_fulfillment_job_id(event_id, attempt_count),
    )
    # ARQ returns None when the deterministic job ID already exists. That still
    # means this event is durably represented in the queue.
    return True


async def process_platform_fulfillment_job(ctx, tenant_id: str, event_id: str):
    result = await ctx["platform_fulfillment_service"].process(
        UUID(tenant_id), UUID(event_id)
    )
    if result.status == "retry_wait" and result.retry_after_seconds is not None:
        raise Retry(defer=result.retry_after_seconds)
    return {
        "status": result.status,
        "attemptCount": result.attempt_count,
    }


async def enqueue_due_platform_fulfillments(ctx) -> int:
    service = ctx["platform_fulfillment_service"]
    repository = ctx["platform_fulfillment_outbox_repository"]
    records = await repository.list_due(processing_timeout=service.processing_timeout)
    queued = 0
    for tenant_id, event_id, attempt_count in records:
        accepted = await enqueue_platform_fulfillment(
            ctx["redis"],
            str(tenant_id),
            str(event_id),
            attempt_count=attempt_count,
        )
        queued += int(accepted)
    return queued
