from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import update

from erp_api.infrastructure.database import Database
from erp_api.models.sample_ingest_batch import SampleIngestBatch
from erp_api.models.sample_sync_run import SampleSyncRun


class SampleSyncAuditRepository:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def start(
        self,
        *,
        tenant_id: UUID,
        shop_id: UUID,
        source_identity: str,
        sync_type: str,
        started_at: datetime,
        source_type: str = "official_api",
        sample_type: str = "free",
    ) -> tuple[UUID, UUID]:
        if source_type not in {"official_api", "hubstudio_cdp"}:
            raise ValueError("Sample audit source type is invalid.")
        batch_id = uuid4()
        run_id = uuid4()
        async with self._database.system_session_factory() as session:
            session.add(
                SampleIngestBatch(
                    id=batch_id,
                    tenant_id=tenant_id,
                    shop_id=shop_id,
                    source_type=source_type,
                    sample_type=sample_type,
                    source_identity=source_identity,
                    status="running",
                    started_at=started_at.astimezone(UTC),
                )
            )
            session.add(
                SampleSyncRun(
                    id=run_id,
                    tenant_id=tenant_id,
                    shop_id=shop_id,
                    sync_type=sync_type,
                    sample_type=sample_type,
                    source_type=source_type,
                    status="running",
                    source_batch_ids=[str(batch_id)],
                    started_at=started_at.astimezone(UTC),
                )
            )
            await session.commit()
        return batch_id, run_id

    async def finish(
        self,
        *,
        tenant_id: UUID,
        shop_id: UUID,
        batch_id: UUID,
        run_id: UUID,
        status: str,
        expected_total: int | None,
        captured_total: int,
        page_count: int,
        payload_hash: str | None,
        request_ids: list[str],
        evidence: dict[str, object],
        error_code: str | None = None,
        error_summary: str | None = None,
        finished_at: datetime,
    ) -> None:
        batch_status = "complete" if status == "succeeded" else status
        completed_at = finished_at.astimezone(UTC)
        async with self._database.system_session_factory() as session:
            await session.execute(
                update(SampleIngestBatch)
                .where(
                    SampleIngestBatch.id == batch_id,
                    SampleIngestBatch.tenant_id == tenant_id,
                    SampleIngestBatch.shop_id == shop_id,
                )
                .values(
                    status=batch_status,
                    expected_total=expected_total,
                    captured_total=captured_total,
                    page_count=page_count,
                    payload_hash=payload_hash,
                    completeness_evidence=evidence,
                    error_code=error_code,
                    error_summary=error_summary,
                    finished_at=completed_at,
                )
            )
            await session.execute(
                update(SampleSyncRun)
                .where(
                    SampleSyncRun.id == run_id,
                    SampleSyncRun.tenant_id == tenant_id,
                    SampleSyncRun.shop_id == shop_id,
                )
                .values(
                    status=status,
                    pages_read=page_count,
                    records_read=captured_total,
                    platform_request_ids=request_ids,
                    error_code=error_code,
                    error_summary=error_summary,
                    finished_at=completed_at,
                )
            )
            await session.commit()

    async def start_feishu(
        self,
        *,
        tenant_id: UUID,
        shop_id: UUID,
        started_at: datetime,
    ) -> UUID:
        run_id = uuid4()
        async with self._database.system_session_factory() as session:
            session.add(
                SampleSyncRun(
                    id=run_id,
                    tenant_id=tenant_id,
                    shop_id=shop_id,
                    sync_type="postgres_to_feishu",
                    source_type="postgresql",
                    status="running",
                    started_at=started_at.astimezone(UTC),
                )
            )
            await session.commit()
        return run_id

    async def finish_feishu(
        self,
        *,
        tenant_id: UUID,
        shop_id: UUID,
        run_id: UUID,
        status: str,
        records_read: int,
        feishu_created: int,
        feishu_updated: int,
        request_ids: list[str],
        error_code: str | None,
        finished_at: datetime,
    ) -> None:
        if status not in {"succeeded", "failed"}:
            raise ValueError("Feishu sample sync status is invalid.")
        async with self._database.system_session_factory() as session:
            result = await session.execute(
                update(SampleSyncRun)
                .where(
                    SampleSyncRun.id == run_id,
                    SampleSyncRun.tenant_id == tenant_id,
                    SampleSyncRun.shop_id == shop_id,
                    SampleSyncRun.sync_type == "postgres_to_feishu",
                    SampleSyncRun.source_type == "postgresql",
                )
                .values(
                    status=status,
                    records_read=records_read,
                    feishu_created=feishu_created,
                    feishu_updated=feishu_updated,
                    platform_request_ids=request_ids,
                    error_code=error_code[:64] if error_code else None,
                    error_summary=(
                        "Feishu sample synchronization failed."
                        if status == "failed"
                        else None
                    ),
                    finished_at=finished_at.astimezone(UTC),
                )
            )
            if result.rowcount != 1:
                raise LookupError("Feishu sample sync run was not found for this shop.")
            await session.commit()
