from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from erp_api.infrastructure.database import Database
from erp_api.models.sample_application import SampleApplication
from erp_api.models.sample_application_event import SampleApplicationEvent
from erp_api.models.sample_application_workflow import SampleApplicationWorkflow
from erp_api.models.sample_notification_outbox import SampleNotificationOutbox


@dataclass(frozen=True)
class AssignmentRemovalTarget:
    creator: str
    application_id: UUID
    platform_application_id: str
    shop_id: UUID
    shop_name: str
    source_record_id: str
    assigned_bd_name: str
    assignment_version: int
    outbox_id: UUID
    outbox_status: str
    assignment_record_id: str


async def suppress_sample_assignments(
    database: Database, assignments: tuple[AssignmentRemovalTarget, ...]
) -> None:
    now = datetime.now(UTC)
    application_ids = tuple(item.application_id for item in assignments)
    async with database.system_session_factory() as session:
        applications = {
            item.id: item
            for item in (
                await session.scalars(
                    select(SampleApplication)
                    .where(SampleApplication.id.in_(application_ids))
                    .with_for_update()
                )
            ).all()
        }
        workflows = {
            item.sample_application_id: item
            for item in (
                await session.scalars(
                    select(SampleApplicationWorkflow)
                    .where(
                        SampleApplicationWorkflow.sample_application_id.in_(
                            application_ids
                        )
                    )
                    .with_for_update()
                )
            ).all()
        }
        outboxes = {
            item.id: item
            for item in (
                await session.scalars(
                    select(SampleNotificationOutbox)
                    .where(
                        SampleNotificationOutbox.id.in_(
                            tuple(item.outbox_id for item in assignments)
                        )
                    )
                    .with_for_update()
                )
            ).all()
        }
        for assignment in assignments:
            application = applications[assignment.application_id]
            workflow = workflows[assignment.application_id]
            outbox = outboxes[assignment.outbox_id]
            raw_payload = dict(application.raw_payload or {})
            raw_payload.update(
                {
                    "manual_assignment_deleted": True,
                    "manual_assignment_deleted_at": now.isoformat(),
                    "manual_assignment_deleted_by": "user_request",
                }
            )
            application.raw_payload = raw_payload
            workflow.assigned_bd_name = None
            workflow.assigned_at = None
            outbox.status = "cancelled"
            outbox.next_attempt_at = None
            await session.execute(
                insert(SampleApplicationEvent)
                .values(
                    tenant_id=application.tenant_id,
                    shop_id=application.shop_id,
                    sample_application_id=application.id,
                    event_type="bd_assignment_removed",
                    event_source="manual_user_request",
                    external_event_id=(
                        f"bd-remove:{application.id}:{assignment.assignment_version}"
                    ),
                    actor_id="codex-user-request",
                    actor_name="User approved in Codex",
                    before_data={"assigned_bd_name": assignment.assigned_bd_name},
                    after_data={
                        "assigned_bd_name": None,
                        "assignment_record_id": assignment.assignment_record_id,
                    },
                    occurred_at=now,
                )
                .on_conflict_do_nothing(
                    constraint=(
                        "uq_sample_application_events_tenant_shop_source_external"
                    )
                )
            )
        await session.commit()
