from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select

from erp_api.infrastructure.database import Database
from erp_api.models.sample_application_workflow import SampleApplicationWorkflow


@dataclass(frozen=True)
class SampleFeishuPollState:
    updated_at: datetime | None
    business_fields: dict[str, str | None]


class SampleFeishuMappingRepository:
    """Persist tenant- and shop-scoped Feishu record mappings."""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def list_poll_states(
        self, record_ids: Sequence[str]
    ) -> dict[str, SampleFeishuPollState]:
        identities = tuple(record_ids)
        if not identities:
            return {}
        if len(identities) > 500 or len(set(identities)) != len(identities):
            raise ValueError("Feishu poll record identities are invalid.")
        async with self._database.system_session_factory() as session:
            rows = (
                await session.execute(
                    select(
                        SampleApplicationWorkflow.feishu_record_id,
                        SampleApplicationWorkflow.feishu_updated_at,
                        SampleApplicationWorkflow.assigned_bd_name,
                        SampleApplicationWorkflow.processing_status,
                        SampleApplicationWorkflow.processing_result,
                        SampleApplicationWorkflow.business_note,
                    ).where(SampleApplicationWorkflow.feishu_record_id.in_(identities))
                )
            ).all()
        return {
            record_id: SampleFeishuPollState(
                updated_at,
                {
                    "分配BD": assigned_bd_name,
                    "处理状态": processing_status,
                    "处理结果": processing_result,
                    "备注": business_note,
                },
            )
            for (
                record_id,
                updated_at,
                assigned_bd_name,
                processing_status,
                processing_result,
                business_note,
            ) in rows
        }

    async def attach_records(
        self,
        *,
        tenant_id: UUID,
        shop_id: UUID,
        mappings: Sequence[tuple[UUID, str]],
    ) -> int:
        pairs = tuple(mappings)
        if not pairs:
            return 0
        by_application: dict[UUID, str] = {}
        record_ids: set[str] = set()
        for application_id, record_id in pairs:
            if application_id in by_application:
                raise ValueError("Sample application mapping is duplicated.")
            if not record_id or len(record_id) > 128 or record_id in record_ids:
                raise ValueError("Feishu record mapping is invalid or duplicated.")
            by_application[application_id] = record_id
            record_ids.add(record_id)

        async with self._database.system_session_factory() as session:
            statement = (
                select(SampleApplicationWorkflow)
                .where(
                    SampleApplicationWorkflow.tenant_id == tenant_id,
                    SampleApplicationWorkflow.shop_id == shop_id,
                    SampleApplicationWorkflow.sample_application_id.in_(by_application),
                )
                .with_for_update()
            )
            workflows = (await session.scalars(statement)).all()
            found = {workflow.sample_application_id for workflow in workflows}
            if found != set(by_application):
                raise LookupError(
                    "Sample application workflow mapping is incomplete for this shop."
                )
            for workflow in workflows:
                record_id = by_application[workflow.sample_application_id]
                if workflow.feishu_record_id not in (None, record_id):
                    raise RuntimeError(
                        "Sample application already has a different Feishu record."
                    )
                workflow.feishu_record_id = record_id
            await session.commit()
        return len(pairs)

    async def detach_records(
        self,
        *,
        tenant_id: UUID,
        shop_id: UUID,
        record_ids: Sequence[str],
    ) -> int:
        identities = tuple(record_ids)
        if not identities:
            return 0
        if (
            len(identities) > 500
            or len(set(identities)) != len(identities)
            or any(not value or len(value) > 128 for value in identities)
        ):
            raise ValueError("Feishu record detach identities are invalid.")
        async with self._database.system_session_factory() as session:
            statement = (
                select(SampleApplicationWorkflow)
                .where(
                    SampleApplicationWorkflow.tenant_id == tenant_id,
                    SampleApplicationWorkflow.shop_id == shop_id,
                    SampleApplicationWorkflow.feishu_record_id.in_(identities),
                )
                .with_for_update()
            )
            workflows = (await session.scalars(statement)).all()
            for workflow in workflows:
                workflow.feishu_record_id = None
                workflow.feishu_updated_at = None
                workflow.sync_hash = None
                workflow.sync_status = "pending"
                workflow.last_sync_at = None
            await session.commit()
        return len(workflows)

    async def mark_synced(
        self,
        *,
        tenant_id: UUID,
        shop_id: UUID,
        records: Sequence[tuple[UUID, str, str]],
        synced_at: datetime,
    ) -> int:
        items = tuple(records)
        if not items:
            return 0
        if (
            len(items) > 500
            or len({item[0] for item in items}) != len(items)
            or any(len(item[2]) != 64 for item in items)
        ):
            raise ValueError("Sample Feishu sync states are invalid.")
        by_application = {
            application_id: (record_id, digest)
            for application_id, record_id, digest in items
        }
        async with self._database.system_session_factory() as session:
            statement = (
                select(SampleApplicationWorkflow)
                .where(
                    SampleApplicationWorkflow.tenant_id == tenant_id,
                    SampleApplicationWorkflow.shop_id == shop_id,
                    SampleApplicationWorkflow.sample_application_id.in_(by_application),
                )
                .with_for_update()
            )
            workflows = (await session.scalars(statement)).all()
            if {row.sample_application_id for row in workflows} != set(by_application):
                raise LookupError(
                    "Sample Feishu sync state is incomplete for this shop."
                )
            for workflow in workflows:
                record_id, digest = by_application[workflow.sample_application_id]
                if workflow.feishu_record_id != record_id:
                    raise RuntimeError(
                        "Sample Feishu sync mapping changed before commit."
                    )
                workflow.last_sync_at = synced_at
                workflow.sync_hash = digest
                workflow.sync_status = "succeeded"
            await session.commit()
        return len(items)

    async def mark_failed(
        self,
        *,
        tenant_id: UUID,
        shop_id: UUID,
        application_ids: Sequence[UUID],
    ) -> int:
        identities = tuple(application_ids)
        if not identities:
            return 0
        if len(identities) > 500 or len(set(identities)) != len(identities):
            raise ValueError("Sample Feishu failed sync identities are invalid.")
        async with self._database.system_session_factory() as session:
            statement = (
                select(SampleApplicationWorkflow)
                .where(
                    SampleApplicationWorkflow.tenant_id == tenant_id,
                    SampleApplicationWorkflow.shop_id == shop_id,
                    SampleApplicationWorkflow.sample_application_id.in_(identities),
                )
                .with_for_update()
            )
            workflows = (await session.scalars(statement)).all()
            if {row.sample_application_id for row in workflows} != set(identities):
                raise LookupError(
                    "Sample Feishu failed sync state is incomplete for this shop."
                )
            for workflow in workflows:
                workflow.sync_status = "failed"
            await session.commit()
        return len(identities)
