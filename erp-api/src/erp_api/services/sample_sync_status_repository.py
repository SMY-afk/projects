from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.sql import Select

from erp_api.infrastructure.database import Database
from erp_api.models.sample_sync_run import SampleSyncRun
from erp_api.models.shop import Shop


@dataclass(frozen=True)
class SampleSyncStatus:
    run_id: UUID
    shop_id: UUID
    shop_name: str
    sync_type: str
    source_type: str
    status: str
    pages_read: int
    records_read: int
    records_created: int
    records_updated: int
    feishu_created: int
    feishu_updated: int
    error_code: str | None
    started_at: datetime
    finished_at: datetime | None


class SampleSyncStatusRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def shop_exists(self, tenant_id: UUID, shop_id: UUID) -> bool:
        async for session in self._database.session(tenant_id):
            found = await session.scalar(
                select(Shop.id).where(
                    Shop.tenant_id == tenant_id,
                    Shop.id == shop_id,
                )
            )
        return found == shop_id

    async def list_recent(
        self,
        tenant_id: UUID,
        *,
        shop_id: UUID | None = None,
        sync_type: str | None = None,
        source_type: str | None = None,
        limit: int = 20,
    ) -> list[SampleSyncStatus]:
        statement = recent_sample_sync_runs_statement(
            tenant_id,
            shop_id=shop_id,
            sync_type=sync_type,
            source_type=source_type,
            limit=limit,
        )
        async for session in self._database.session(tenant_id):
            rows = (await session.execute(statement)).all()
        return [
            SampleSyncStatus(
                run_id=run.id,
                shop_id=run.shop_id,
                shop_name=shop_name,
                sync_type=run.sync_type,
                source_type=run.source_type,
                status=run.status,
                pages_read=run.pages_read,
                records_read=run.records_read,
                records_created=run.records_created,
                records_updated=run.records_updated,
                feishu_created=run.feishu_created,
                feishu_updated=run.feishu_updated,
                error_code=run.error_code,
                started_at=run.started_at,
                finished_at=run.finished_at,
            )
            for run, shop_name in rows
        ]


def recent_sample_sync_runs_statement(
    tenant_id: UUID,
    *,
    shop_id: UUID | None = None,
    sync_type: str | None = None,
    source_type: str | None = None,
    limit: int = 20,
) -> Select:
    statement = (
        select(SampleSyncRun, Shop.shop_name)
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
        )
    )
    if shop_id is not None:
        statement = statement.where(
            SampleSyncRun.shop_id == shop_id,
            Shop.id == shop_id,
        )
    if sync_type is not None:
        statement = statement.where(SampleSyncRun.sync_type == sync_type)
    if source_type is not None:
        statement = statement.where(SampleSyncRun.source_type == source_type)
    return statement.order_by(
        SampleSyncRun.started_at.desc(),
        SampleSyncRun.id.desc(),
    ).limit(limit)
