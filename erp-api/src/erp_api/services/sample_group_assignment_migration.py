from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from erp_api.infrastructure.database import Database
from erp_api.models.sample_application import SampleApplication
from erp_api.models.sample_application_event import SampleApplicationEvent
from erp_api.models.sample_application_workflow import SampleApplicationWorkflow
from erp_api.models.sample_notification_outbox import SampleNotificationOutbox
from erp_api.services.sample_group_assignment_policy import (
    GroupAssignmentBlocked,
    GroupAssignmentCandidate,
    apply_group_assignment_migration,
)


class SampleGroupAssignmentMigrationService:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def migrate(
        self,
        *,
        tenant_id: UUID,
        shop_id: UUID,
        obsolete_platform_application_ids: frozenset[str],
    ) -> frozenset[UUID]:
        if not obsolete_platform_application_ids:
            return frozenset()
        async with self._database.system_session_factory() as session:
            children = tuple(
                (
                    await session.scalars(
                        select(SampleApplication)
                        .where(
                            SampleApplication.tenant_id == tenant_id,
                            SampleApplication.shop_id == shop_id,
                            SampleApplication.platform_application_id.in_(
                                obsolete_platform_application_ids
                            ),
                        )
                        .with_for_update()
                    )
                ).all()
            )
            grouped = _children_by_parent(children)
            if not grouped:
                return frozenset()
            parents = tuple(
                (
                    await session.scalars(
                        select(SampleApplication)
                        .where(
                            SampleApplication.tenant_id == tenant_id,
                            SampleApplication.shop_id == shop_id,
                            SampleApplication.platform_application_id.in_(grouped),
                            SampleApplication.is_current_projection.is_(True),
                        )
                        .with_for_update()
                    )
                ).all()
            )
            parents_by_platform_id = {
                item.platform_application_id: item for item in parents
            }
            application_ids = tuple(
                {item.id for item in children} | {item.id for item in parents}
            )
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
            outboxes = tuple(
                (
                    await session.scalars(
                        select(SampleNotificationOutbox)
                        .where(
                            SampleNotificationOutbox.sample_application_id.in_(
                                application_ids
                            ),
                            SampleNotificationOutbox.status != "cancelled",
                        )
                        .with_for_update()
                    )
                ).all()
            )
            active_outboxes = _latest_active_outboxes(workflows, outboxes)
            migrated: set[UUID] = set()
            now = datetime.now(UTC)
            for parent_platform_id, group_children in grouped.items():
                parent = parents_by_platform_id.get(parent_platform_id)
                if parent is None:
                    raise RuntimeError("Grouped sample parent application is unavailable.")
                parent_workflow = workflows[parent.id]
                candidates = tuple(
                    GroupAssignmentCandidate(
                        child,
                        workflows[child.id],
                        active_outboxes[child.id],
                    )
                    for child in group_children
                    if workflows[child.id].assigned_bd_name
                    and child.id in active_outboxes
                )
                result = apply_group_assignment_migration(
                    parent,
                    parent_workflow,
                    parent_outbox=active_outboxes.get(parent.id),
                    child_candidates=candidates,
                )
                if result is None:
                    continue
                if isinstance(result, GroupAssignmentBlocked):
                    await session.execute(
                        insert(SampleApplicationEvent)
                        .values(
                            tenant_id=tenant_id,
                            shop_id=shop_id,
                            sample_application_id=parent.id,
                            event_type="bd_assignment_projection_blocked",
                            event_source="erp_group_projection",
                            external_event_id=(
                                f"group-assignment-blocked:{parent.id}:{result.reason}"
                            ),
                            actor_name="ERP Group Projection",
                            before_data={
                                "assigned_bd_name": parent_workflow.assigned_bd_name
                            },
                            after_data={
                                "reason": result.reason,
                                "assigned_bd_names": list(result.bd_names),
                                "application_ids": [
                                    str(item) for item in result.application_ids
                                ],
                            },
                            occurred_at=now,
                        )
                        .on_conflict_do_nothing(
                            constraint=(
                                "uq_sample_application_events_tenant_shop_source_external"
                            )
                        )
                    )
                    continue
                migrated.add(parent.id)
                await session.execute(
                    insert(SampleApplicationEvent)
                    .values(
                        tenant_id=tenant_id,
                        shop_id=shop_id,
                        sample_application_id=parent.id,
                        event_type="bd_assignment_projection_migrated",
                        event_source="erp_group_projection",
                        external_event_id=(
                            f"group-assignment:{parent.id}:"
                            f"{result.canonical_outbox.id}"
                        ),
                        actor_name="ERP Group Projection",
                        before_data={"assigned_bd_name": None},
                        after_data={
                            "assigned_bd_name": parent_workflow.assigned_bd_name,
                            "source_application_id": str(
                                result.source_application_id
                            ),
                            "assignment_outbox_id": str(
                                result.canonical_outbox.id
                            ),
                            "cancelled_outbox_ids": [
                                str(item) for item in result.cancelled_outbox_ids
                            ],
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
        return frozenset(migrated)


def _children_by_parent(children):
    grouped: dict[str, list[SampleApplication]] = defaultdict(list)
    for child in children:
        payload = child.raw_payload if isinstance(child.raw_payload, dict) else {}
        projection = payload.get("ziniao_group_projection")
        parent_id = (
            projection.get("parent_application_id")
            if isinstance(projection, dict)
            else None
        )
        if isinstance(parent_id, str) and parent_id:
            grouped[parent_id].append(child)
    return {key: tuple(value) for key, value in grouped.items()}


def _latest_active_outboxes(workflows, outboxes):
    latest = {}
    for outbox in outboxes:
        if outbox.sample_application_id not in workflows:
            continue
        existing = latest.get(outbox.sample_application_id)
        if existing is None or _outbox_order(outbox) > _outbox_order(existing):
            latest[outbox.sample_application_id] = outbox
    return latest


def _outbox_order(outbox: SampleNotificationOutbox):
    never = datetime.min.replace(tzinfo=UTC)
    return (
        outbox.assignment_version,
        outbox.created_at or never,
        str(outbox.id),
    )


def _candidate_order(item: GroupAssignmentCandidate):
    never = datetime.max.replace(tzinfo=UTC)
    return (
        item.workflow.assigned_at or item.outbox.created_at or never,
        item.outbox.created_at or never,
        str(item.outbox.id),
    )


def _assignment_record_id(outbox: SampleNotificationOutbox) -> str | None:
    payload = outbox.payload if isinstance(outbox.payload, dict) else {}
    value = payload.get("assignment_record_id")
    return value.strip() if isinstance(value, str) and value.strip() else None
