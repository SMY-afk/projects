from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import or_, select

from erp_api.infrastructure.database import Database
from erp_api.models.sample_application import SampleApplication
from erp_api.models.sample_application_event import SampleApplicationEvent
from erp_api.models.sample_application_workflow import SampleApplicationWorkflow
from erp_api.services.feishu_sample_change import parse_feishu_assignee
from erp_api.services.refundable_identity_guard import refundable_identity_condition


@dataclass(frozen=True)
class SampleAssignmentProjectionResult:
    updated_count: int


class SampleAutoAssignmentFeishuService:
    def __init__(self, database: Database, client, *, limit: int = 100) -> None:
        if not 1 <= limit <= 100:
            raise ValueError("Sample assignment projection limit is invalid.")
        self._database = database
        self._client = client
        self._limit = limit

    async def sync(
        self, *, tenant_id: UUID, shop_id: UUID, verify_current: bool = False
    ) -> SampleAssignmentProjectionResult:
        targets = await self._list_targets(tenant_id, shop_id, verify_current)
        client = (
            self._client.for_shop(shop_id)
            if hasattr(self._client, "for_shop")
            else self._client
        )
        if not targets:
            return SampleAssignmentProjectionResult(0)
        if verify_current:
            stale = []
            for target in targets:
                _workflow_id, record_id, bd_name, processing_status, _occurred_at = target
                current = await client.get_record(record_id)
                if (
                    parse_feishu_assignee(current.get("分配BD")).name != bd_name
                    or current.get("处理状态") != processing_status
                ):
                    stale.append(target)
            targets = tuple(stale)
            if not targets:
                return SampleAssignmentProjectionResult(0)
        updates = [
            (record_id, {"分配BD": bd_name, "处理状态": processing_status})
            for _workflow_id, record_id, bd_name, processing_status, _occurred_at in targets
        ]
        updated = await client.batch_update_business_fields(updates)
        await self._mark_projected(
            tenant_id=tenant_id,
            shop_id=shop_id,
            targets=targets,
            projected_at=datetime.now(UTC),
        )
        return SampleAssignmentProjectionResult(len(updated))

    async def _list_targets(
        self, tenant_id: UUID, shop_id: UUID, verify_current: bool = False
    ):
        statement = (
            select(
                SampleApplicationWorkflow.id,
                SampleApplicationWorkflow.feishu_record_id,
                SampleApplicationWorkflow.assigned_bd_name,
                SampleApplicationWorkflow.processing_status,
                SampleApplicationEvent.occurred_at,
            )
            .join(
                SampleApplicationEvent,
                SampleApplicationEvent.sample_application_id
                == SampleApplicationWorkflow.sample_application_id,
            )
            .join(
                SampleApplication,
                SampleApplication.id == SampleApplicationWorkflow.sample_application_id,
            )
            .where(
                SampleApplicationWorkflow.tenant_id == tenant_id,
                SampleApplicationWorkflow.shop_id == shop_id,
                SampleApplicationWorkflow.feishu_record_id.is_not(None),
                SampleApplicationWorkflow.assigned_bd_name.is_not(None),
                SampleApplication.is_current_projection.is_(True),
                refundable_identity_condition(SampleApplication),
                SampleApplicationEvent.tenant_id == tenant_id,
                SampleApplicationEvent.shop_id == shop_id,
                SampleApplicationEvent.event_type.in_(
                    (
                        "bd_auto_assigned",
                        "bd_assignment_projection_migrated",
                    )
                ),
            )
            .order_by(SampleApplicationEvent.occurred_at)
            .limit(self._limit)
        )
        if not verify_current:
            statement = statement.where(
                or_(
                    SampleApplicationWorkflow.feishu_updated_at.is_(None),
                    SampleApplicationWorkflow.feishu_updated_at
                    < SampleApplicationEvent.occurred_at,
                )
            )
        async with self._database.system_session_factory() as session:
            rows = (await session.execute(statement)).all()
        unique = {}
        for row in rows:
            unique[row.id] = (
                row.id,
                row.feishu_record_id,
                row.assigned_bd_name,
                row.processing_status,
                row.occurred_at,
            )
        return tuple(unique.values())

    async def _mark_projected(
        self,
        *,
        tenant_id: UUID,
        shop_id: UUID,
        targets,
        projected_at: datetime,
    ) -> None:
        by_workflow = {
            workflow_id: max(projected_at, occurred_at)
            for workflow_id, _record_id, _bd_name, _status, occurred_at in targets
        }
        async with self._database.system_session_factory() as session:
            workflows = (
                await session.scalars(
                    select(SampleApplicationWorkflow)
                    .where(
                        SampleApplicationWorkflow.id.in_(by_workflow),
                        SampleApplicationWorkflow.tenant_id == tenant_id,
                        SampleApplicationWorkflow.shop_id == shop_id,
                    )
                    .with_for_update()
                )
            ).all()
            if {workflow.id for workflow in workflows} != set(by_workflow):
                raise LookupError("Projected sample workflows were not found.")
            for workflow in workflows:
                workflow.feishu_updated_at = by_workflow[workflow.id]
            await session.commit()
