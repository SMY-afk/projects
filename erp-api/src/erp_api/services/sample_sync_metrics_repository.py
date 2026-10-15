from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, case, func, select
from sqlalchemy.sql import Select

from erp_api.infrastructure.database import Database
from erp_api.models.sample_sync_run import SampleSyncRun
from erp_api.models.shop import Shop


@dataclass(frozen=True)
class SampleSyncMetrics:
    shop_id: UUID
    shop_name: str
    sync_type: str
    source_type: str
    run_count: int
    queued_count: int
    succeeded_count: int
    partial_count: int
    failed_count: int
    running_count: int
    records_read: int
    records_created: int
    records_updated: int
    feishu_created: int
    feishu_updated: int
    average_duration_seconds: float | None
    last_succeeded_at: datetime | None
    last_failed_at: datetime | None


class SampleSyncMetricsRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def list_metrics(
        self,
        tenant_id: UUID,
        *,
        shop_id: UUID | None = None,
        sync_type: str | None = None,
        source_type: str | None = None,
        window_hours: int = 24,
        now: datetime | None = None,
    ) -> list[SampleSyncMetrics]:
        cutoff = (now or datetime.now(UTC)).astimezone(UTC) - timedelta(
            hours=window_hours
        )
        statement = sample_sync_metrics_statement(
            tenant_id,
            cutoff=cutoff,
            shop_id=shop_id,
            sync_type=sync_type,
            source_type=source_type,
        )
        async for session in self._database.session(tenant_id):
            rows = (await session.execute(statement)).all()
        return [SampleSyncMetrics(*row) for row in rows]


def sample_sync_metrics_statement(
    tenant_id: UUID,
    *,
    cutoff: datetime,
    shop_id: UUID | None = None,
    sync_type: str | None = None,
    source_type: str | None = None,
) -> Select:
    duration = func.extract(
        "epoch", SampleSyncRun.finished_at - SampleSyncRun.started_at
    )
    statement = (
        select(
            SampleSyncRun.shop_id,
            Shop.shop_name,
            SampleSyncRun.sync_type,
            SampleSyncRun.source_type,
            func.count(SampleSyncRun.id),
            _status_count("queued"),
            _status_count("succeeded"),
            _status_count("partial"),
            _status_count("failed"),
            _status_count("running"),
            _sum(SampleSyncRun.records_read),
            _sum(SampleSyncRun.records_created),
            _sum(SampleSyncRun.records_updated),
            _sum(SampleSyncRun.feishu_created),
            _sum(SampleSyncRun.feishu_updated),
            func.avg(duration).filter(SampleSyncRun.finished_at.is_not(None)),
            func.max(
                case(
                    (SampleSyncRun.status == "succeeded", SampleSyncRun.finished_at)
                )
            ),
            func.max(
                case(
                    (
                        SampleSyncRun.status.in_(("partial", "failed")),
                        SampleSyncRun.finished_at,
                    )
                )
            ),
        )
        .join(
            Shop,
            and_(
                Shop.id == SampleSyncRun.shop_id,
                Shop.tenant_id == SampleSyncRun.tenant_id,
            ),
        )
        .where(
            SampleSyncRun.tenant_id == tenant_id,
            Shop.tenant_id == tenant_id,
            SampleSyncRun.started_at >= cutoff,
        )
    )
    if shop_id is not None:
        statement = statement.where(SampleSyncRun.shop_id == shop_id)
    if sync_type is not None:
        statement = statement.where(SampleSyncRun.sync_type == sync_type)
    if source_type is not None:
        statement = statement.where(SampleSyncRun.source_type == source_type)
    return statement.group_by(
        SampleSyncRun.shop_id,
        Shop.shop_name,
        SampleSyncRun.sync_type,
        SampleSyncRun.source_type,
    ).order_by(Shop.shop_name, SampleSyncRun.sync_type, SampleSyncRun.source_type)


def _status_count(status: str):
    return func.count(SampleSyncRun.id).filter(SampleSyncRun.status == status)


def _sum(column):
    return func.coalesce(func.sum(column), 0)
