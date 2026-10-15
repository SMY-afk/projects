from uuid import UUID


async def poll_logistics_tracking_job(ctx, tenant_id: str, waybill_id: str):
    try:
        result = await ctx["logistics_tracking_service"].poll(
            UUID(tenant_id), UUID(waybill_id)
        )
    except Exception as error:  # noqa: BLE001 - service persisted safe error state
        return {"status": "retry_wait", "errorCode": type(error).__name__[:64]}
    return {"status": "succeeded", **result}


async def enqueue_due_logistics_tracking_polls(ctx) -> int:
    repository = ctx["logistics_tracking_repository"]
    records = await repository.list_due_polls()
    queued = 0
    for tenant_id, waybill_id, attempt_count in records:
        job = await ctx["redis"].enqueue_job(
            "poll_logistics_tracking_job",
            str(tenant_id),
            str(waybill_id),
            _job_id=f"logistics-tracking:{waybill_id}:{attempt_count}",
        )
        queued += int(job is not None)
    return queued


async def detect_logistics_exceptions_job(ctx) -> dict[str, int]:
    return await ctx["logistics_exception_service"].scan_all()


async def sync_tiktok_logistics_job(ctx) -> dict[str, int | str]:
    service = ctx.get("platform_logistics_sync_service")
    if service is None:
        return {"status": "disabled"}
    return {"status": "succeeded", **await service.sync_all()}
