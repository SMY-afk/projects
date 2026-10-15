from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select

from erp_api.infrastructure.database import Database
from erp_api.models.sample_sync_run import SampleSyncRun
from erp_api.services.affiliate_schedule_queries import (
    latest_due_capture_window_start,
)


def sample_round_allows_affiliate(
    *,
    sample_status: str | None,
    sample_finished_at: datetime | None,
    window_start: datetime,
) -> bool:
    return (
        sample_status == "succeeded"
        and sample_finished_at is not None
        and sample_finished_at >= window_start
    )


async def sample_round_releases_affiliate(
    database: Database,
    tenant_id: UUID,
    shop_id: UUID,
    *,
    now: datetime,
) -> bool:
    window_start = latest_due_capture_window_start(now)
    async with database.system_session_factory() as session:
        latest_sample = await session.scalar(
            select(SampleSyncRun)
            .where(
                SampleSyncRun.tenant_id == tenant_id,
                SampleSyncRun.shop_id == shop_id,
                SampleSyncRun.sync_type == "source_to_postgres",
                SampleSyncRun.started_at >= window_start,
            )
            .order_by(SampleSyncRun.started_at.desc())
            .limit(1)
        )
    return sample_round_allows_affiliate(
        sample_status=latest_sample.status if latest_sample else None,
        sample_finished_at=latest_sample.finished_at if latest_sample else None,
        window_start=window_start,
    )
