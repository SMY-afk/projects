from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from uuid import UUID

from arq import Retry
from sqlalchemy import select

from erp_api.models.shop import Shop
from erp_api.models.shop_connection import ShopConnection
from erp_api.services.sample_application_mapper import (
    ACTIVE_SAMPLE_STATUSES,
    TERMINAL_SAMPLE_STATUSES,
)
from erp_api.services.sample_observability import (
    log_sample_sync_failure,
    log_sample_sync_success,
)
from erp_api.services.sample_source_policy import SAMPLE_APPLICATION_SCOPE
from erp_api.workers.sample_notification_jobs import send_sample_notification_job

__all__ = ["send_sample_notification_job"]

logger = logging.getLogger("erp_api.sample_sync")


async def sync_sample_applications_job(
    ctx,
    tenant_id: str,
    shop_id: str,
    mode: str,
    statuses: list[str | None],
    source_type: str = "official_api",
    dry_run: bool = False,
):
    if mode not in {"active", "terminal"}:
        raise ValueError("Fast sample sync mode is invalid.")
    return await _run_shop_pipeline(
        ctx,
        tenant_id,
        shop_id,
        mode=mode,
        statuses=statuses,
        source_type=source_type,
        dry_run=dry_run,
    )


async def reconcile_sample_applications_job(
    ctx,
    tenant_id: str,
    shop_id: str,
    source_type: str = "official_api",
    dry_run: bool = False,
):
    return await _run_shop_pipeline(
        ctx,
        tenant_id,
        shop_id,
        mode="full",
        statuses=[None],
        source_type=source_type,
        dry_run=dry_run,
    )


async def recover_sample_application_source_job(
    ctx,
    tenant_id: str,
    shop_id: str,
):
    service = ctx.get("sample_source_recovery_service")
    if service is None:
        raise RuntimeError("Sample source recovery service is unavailable.")
    lock = ctx.get("sample_shop_sync_lock")
    if lock is None:
        raise RuntimeError("Sample shop sync lock is unavailable.")
    parsed_tenant_id = UUID(tenant_id)
    parsed_shop_id = UUID(shop_id)
    async with lock.acquire(parsed_tenant_id, parsed_shop_id) as acquired:
        if not acquired:
            raise Retry(defer=ctx.get("sample_shop_lock_retry_seconds", 30))
        return await service.recover(parsed_tenant_id, parsed_shop_id)


async def poll_feishu_sample_business_fields_job(ctx, full_scan: bool = True):
    service = ctx.get("feishu_sample_reverse_poll_service")
    if service is None:
        raise RuntimeError("Feishu sample reverse poll service is unavailable.")
    return await service.poll(full_scan=full_scan)


async def enqueue_feishu_sample_reverse_poll(ctx) -> int:
    if ctx.get("feishu_sample_reverse_poll_service") is None:
        return 0
    now = _now(ctx)
    job = await ctx["redis"].enqueue_job(
        "poll_feishu_sample_business_fields_job",
        False,
        _job_id=f"feishu-sample-reverse-poll:{now:%Y%m%d%H%M}",
    )
    return int(job is not None)


async def enqueue_feishu_sample_reverse_poll_audit(ctx) -> int:
    if ctx.get("feishu_sample_reverse_poll_service") is None:
        return 0
    now = _now(ctx)
    job = await ctx["redis"].enqueue_job(
        "poll_feishu_sample_business_fields_job",
        True,
        _job_id=f"feishu-sample-reverse-poll-audit:{now:%Y%m%d}",
    )
    return int(job is not None)


async def enqueue_due_sample_notifications(ctx) -> int:
    service = ctx.get("sample_notification_service")
    if service is None:
        return 0
    now = _now(ctx)
    queued = 0
    for tenant_id, event_id, attempt_count in await service.list_due():
        job = await ctx["redis"].enqueue_job(
            "send_sample_notification_job",
            str(tenant_id),
            str(event_id),
            _job_id=(
                f"sample-notification:{event_id}:{attempt_count + 1}:"
                f"{now:%Y%m%d%H%M}"
            ),
        )
        if job is not None:
            queued += 1
    return queued


async def reconcile_failed_sample_notifications(ctx) -> int:
    repository = ctx.get("sample_notification_repository")
    if repository is None:
        return 0
    return await repository.requeue_current_failures(now=_now(ctx))


async def enqueue_active_sample_application_polls(ctx) -> int:
    return await _enqueue(ctx, "active", sorted(ACTIVE_SAMPLE_STATUSES))


async def enqueue_terminal_sample_application_polls(ctx) -> int:
    return await _enqueue(ctx, "terminal", sorted(TERMINAL_SAMPLE_STATUSES))


async def enqueue_sample_application_reconciliation(ctx) -> int:
    return await _enqueue(ctx, "full", [None])


async def enqueue_sample_source_recoveries(ctx) -> int:
    service = ctx.get("sample_source_recovery_service")
    if service is None:
        return 0
    now = _now(ctx)
    queued = 0
    for tenant_id, shop_id in await service.candidates():
        job = await ctx["redis"].enqueue_job(
            "recover_sample_application_source_job",
            str(tenant_id),
            str(shop_id),
            _job_id=(f"sample-source-recovery:{shop_id}:{_bucket(now, 'active')}"),
        )
        if job is not None:
            queued += 1
    return queued


async def _enqueue(ctx, mode: str, statuses: list[str | None]) -> int:
    now = _now(ctx)
    queued = 0
    for tenant_id, shop_id in await _authorized_sample_shops(ctx["database"]):
        bucket = _bucket(now, mode)
        job_id = f"sample-applications:{tenant_id}:{shop_id}:{mode}:{bucket}"
        if mode == "full":
            job = await ctx["redis"].enqueue_job(
                "reconcile_sample_applications_job",
                str(tenant_id),
                str(shop_id),
                "official_api",
                False,
                _job_id=job_id,
            )
        else:
            job = await ctx["redis"].enqueue_job(
                "sync_sample_applications_job",
                str(tenant_id),
                str(shop_id),
                mode,
                statuses,
                "official_api",
                False,
                _job_id=job_id,
            )
        if job is not None:
            queued += 1
    return queued


async def _run_shop_pipeline(
    ctx,
    tenant_id: str,
    shop_id: str,
    *,
    mode: str,
    statuses: list[str | None],
    source_type: str,
    dry_run: bool,
):
    started_at = time.perf_counter()
    request_id = str(ctx.get("job_id") or "unavailable")
    try:
        service = ctx.get("sample_shop_pipeline_service")
        if service is None:
            raise RuntimeError("Sample shop pipeline service is unavailable.")
        lock = ctx.get("sample_shop_sync_lock")
        if lock is None:
            raise RuntimeError("Sample shop sync lock is unavailable.")
        if not statuses:
            raise ValueError("Sample application sync statuses must not be empty.")
        parsed_tenant_id = UUID(tenant_id)
        parsed_shop_id = UUID(shop_id)
        async with lock.acquire(parsed_tenant_id, parsed_shop_id) as acquired:
            if not acquired:
                raise Retry(defer=ctx.get("sample_shop_lock_retry_seconds", 30))
            result = await service.run(
                parsed_tenant_id,
                parsed_shop_id,
                mode=mode,
                statuses=statuses,
                source_type=source_type,
                dry_run=dry_run,
            )
    except Exception as error:
        log_sample_sync_failure(
            logger,
            tenant_id=tenant_id,
            shop_id=shop_id,
            request_id=request_id,
            duration_ms=(time.perf_counter() - started_at) * 1000,
            error=error,
        )
        raise
    log_sample_sync_success(
        logger,
        tenant_id=tenant_id,
        shop_id=shop_id,
        request_id=request_id,
        duration_ms=(time.perf_counter() - started_at) * 1000,
        result=result,
    )
    return result


async def _authorized_sample_shops(database) -> list[tuple[UUID, UUID]]:
    async with database.system_session_factory() as session:
        rows = (
            await session.execute(
                select(
                    Shop.tenant_id,
                    Shop.id,
                    ShopConnection.scopes,
                )
                .join(
                    ShopConnection,
                    (ShopConnection.shop_id == Shop.id)
                    & (ShopConnection.tenant_id == Shop.tenant_id),
                )
                .where(
                    Shop.platform == "tiktok",
                    Shop.status == "active",
                    ShopConnection.auth_status == "authorized",
                )
                .order_by(Shop.tenant_id, Shop.id)
            )
        ).all()
    return [
        (tenant_id, shop_id)
        for tenant_id, shop_id, scopes in rows
        if SAMPLE_APPLICATION_SCOPE in (scopes or [])
    ]


def _bucket(now: datetime, mode: str) -> str:
    if mode == "active":
        return now.strftime("%Y%m%d%H") + f"{now.minute // 5:02d}"
    if mode == "terminal":
        return now.strftime("%Y%m%d%H")
    return now.strftime("%Y%m%d")


def _now(ctx) -> datetime:
    value = ctx.get("now")
    return value.astimezone(UTC) if isinstance(value, datetime) else datetime.now(UTC)
