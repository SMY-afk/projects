from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from erp_api.models.sample_application import SampleApplication
from erp_api.models.sample_application_workflow import SampleApplicationWorkflow
from erp_api.models.sample_notification_outbox import SampleNotificationOutbox


@dataclass(frozen=True)
class GroupAssignmentCandidate:
    application: SampleApplication
    workflow: SampleApplicationWorkflow
    outbox: SampleNotificationOutbox


@dataclass(frozen=True)
class GroupAssignmentMigration:
    canonical_outbox: SampleNotificationOutbox
    source_application_id: UUID
    cancelled_outbox_ids: tuple[UUID, ...]


@dataclass(frozen=True)
class GroupAssignmentBlocked:
    reason: str
    bd_names: tuple[str, ...]
    application_ids: tuple[UUID, ...]


def apply_group_assignment_migration(
    parent: SampleApplication,
    parent_workflow: SampleApplicationWorkflow,
    *,
    parent_outbox: SampleNotificationOutbox | None,
    child_candidates: tuple[GroupAssignmentCandidate, ...],
) -> GroupAssignmentMigration | GroupAssignmentBlocked | None:
    children = tuple(
        item for item in child_candidates if item.outbox.status != "cancelled"
    )
    if not children:
        return None
    participants = _participants(parent, parent_workflow, parent_outbox, children)
    bd_names = tuple(
        sorted(
            {
                item.workflow.assigned_bd_name
                for item in participants
                if item.workflow.assigned_bd_name
            }
        )
    )
    delivered = tuple(
        item
        for item in participants
        if item.workflow.assigned_bd_name and _has_delivery_evidence(item.outbox)
    )
    delivered_bds = {
        item.workflow.assigned_bd_name for item in delivered if item.workflow.assigned_bd_name
    }
    if len(delivered_bds) > 1:
        return _blocked("multiple_delivered_bds", bd_names, participants)
    selected = _select_candidate(parent, parent_outbox, participants, delivered)
    if selected is None:
        if len(bd_names) > 1:
            return _blocked("no_delivery_evidence", bd_names, participants)
        selected = min(participants, key=_candidate_order)
    canonical = selected.outbox
    record_ids = {
        record_id
        for item in participants
        if (record_id := _assignment_record_id(item.outbox)) is not None
    }
    if len(record_ids) > 1:
        return _blocked("different_feishu_record_ids", bd_names, participants)

    bd_name = selected.workflow.assigned_bd_name
    if not bd_name:
        return _blocked("missing_selected_bd", bd_names, participants)
    if selected.application.id != parent.id or parent_workflow.assigned_bd_name != bd_name:
        parent_workflow.assigned_bd_name = bd_name
        parent_workflow.processing_status = selected.workflow.processing_status
        parent_workflow.processing_result = selected.workflow.processing_result
        parent_workflow.business_note = selected.workflow.business_note
        parent_workflow.assigned_at = selected.workflow.assigned_at or canonical.created_at
        parent_workflow.assignment_version = max(
            parent_workflow.assignment_version + 1,
            canonical.assignment_version,
        )
    canonical.sample_application_id = parent.id
    canonical.assignment_version = parent_workflow.assignment_version
    payload = dict(canonical.payload or {})
    payload["assigned_bd_name"] = bd_name
    payload["group_migrated_from_application_id"] = str(selected.application.id)
    payload["group_migrated_to_application_id"] = str(parent.id)
    if record_ids:
        payload["assignment_record_id"] = next(iter(record_ids))
    canonical.payload = payload

    cancelled = []
    for item in participants:
        if item.outbox is canonical:
            continue
        item.outbox.status = "cancelled"
        item.outbox.next_attempt_at = None
        item.outbox.last_error_code = "superseded_group_assignment"
        item.outbox.last_error_summary = (
            "The assignment was consolidated into the current grouped application."
        )
        cancelled.append(item.outbox.id)
    return GroupAssignmentMigration(
        canonical_outbox=canonical,
        source_application_id=selected.application.id,
        cancelled_outbox_ids=tuple(cancelled),
    )


def _participants(parent, parent_workflow, parent_outbox, children):
    items = list(children)
    if parent_outbox is not None and parent_outbox.status != "cancelled":
        items.append(GroupAssignmentCandidate(parent, parent_workflow, parent_outbox))
    return tuple(items)


def _select_candidate(parent, parent_outbox, participants, delivered):
    if parent_outbox is not None:
        current_parent = next(
            (item for item in participants if item.application.id == parent.id), None
        )
        if current_parent is not None and _has_delivery_evidence(parent_outbox):
            return current_parent
    if delivered:
        return min(delivered, key=_candidate_order)
    return None


def _blocked(reason, bd_names, participants):
    return GroupAssignmentBlocked(
        reason=reason,
        bd_names=bd_names,
        application_ids=tuple(item.application.id for item in participants),
    )


def _has_delivery_evidence(outbox: SampleNotificationOutbox) -> bool:
    if outbox.status == "sent":
        return True
    payload = outbox.payload if isinstance(outbox.payload, dict) else {}
    return bool(payload.get("message_id") and payload.get("message_sent_at"))


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
