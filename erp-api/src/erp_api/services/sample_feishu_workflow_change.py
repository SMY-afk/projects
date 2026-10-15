from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert

from erp_api.models.sample_notification_outbox import SampleNotificationOutbox
from erp_api.services.feishu_sample_fields import BUSINESS_FIELDS


@dataclass(frozen=True)
class WorkflowBusinessProjection:
    before: dict[str, Any]
    after: dict[str, Any]

    @property
    def assignment_changed(self) -> bool:
        return self.before["assigned_bd_name"] != self.after["assigned_bd_name"]


def validate_feishu_business_update(
    *,
    record_id: str,
    fields: dict[str, Any],
    event_id: str,
    event_source: str,
    assignment_recipient_open_id: str | None,
    occurred_at: datetime,
) -> None:
    if not fields or not set(fields) <= BUSINESS_FIELDS:
        raise ValueError("Only non-empty Feishu business fields are allowed.")
    if any(
        value is not None and not isinstance(value, str) for value in fields.values()
    ):
        raise ValueError("Feishu business field values must be text or null.")
    if fields.get("分配BD") and (
        not assignment_recipient_open_id or len(assignment_recipient_open_id) > 255
    ):
        raise ValueError("Feishu BD assignment recipient is invalid.")
    if (
        not event_id
        or len(event_id) > 255
        or any(character.isspace() for character in event_id)
        or event_source not in {"feishu_callback", "feishu_poll"}
    ):
        raise ValueError("Feishu event identity is invalid.")
    if not record_id or len(record_id) > 128:
        raise ValueError("Feishu record identity is invalid.")
    if occurred_at.tzinfo is None:
        raise ValueError("Feishu event timestamp must include a UTC offset.")


def project_workflow_business_fields(
    workflow, fields: dict[str, Any]
) -> WorkflowBusinessProjection:
    before = {
        "assigned_bd_name": workflow.assigned_bd_name,
        "processing_status": workflow.processing_status,
        "processing_result": workflow.processing_result,
        "business_note": workflow.business_note,
    }
    after = dict(before)
    field_attributes = {
        "分配BD": "assigned_bd_name",
        "处理状态": "processing_status",
        "处理结果": "processing_result",
        "备注": "business_note",
    }
    for field_name, value in fields.items():
        after[field_attributes[field_name]] = value or None
    return WorkflowBusinessProjection(before, after)


def build_notification_outbox_statements(
    workflow,
    *,
    record_id: str,
    recipient_open_id: str | None,
    event_id: str,
    occurred_at: datetime,
    assignment_notice: str | None = None,
):
    cancel = (
        update(SampleNotificationOutbox)
        .where(
            SampleNotificationOutbox.tenant_id == workflow.tenant_id,
            SampleNotificationOutbox.shop_id == workflow.shop_id,
            SampleNotificationOutbox.sample_application_id
            == workflow.sample_application_id,
            SampleNotificationOutbox.assignment_version < workflow.assignment_version,
            SampleNotificationOutbox.status.in_(
                {"pending", "processing", "retry_wait"}
            ),
        )
        .values(status="cancelled", next_attempt_at=None)
    )
    if recipient_open_id is None:
        return cancel, None
    payload = {
        "feishu_record_id": record_id,
        "assigned_bd_name": workflow.assigned_bd_name,
        "source_event_id": event_id,
    }
    if assignment_notice:
        payload["assignment_notice"] = assignment_notice
    create = (
        insert(SampleNotificationOutbox)
        .values(
            tenant_id=workflow.tenant_id,
            shop_id=workflow.shop_id,
            sample_application_id=workflow.sample_application_id,
            assignment_version=workflow.assignment_version,
            recipient_open_id=recipient_open_id,
            payload=payload,
            status="pending",
            attempt_count=0,
            next_attempt_at=occurred_at,
        )
        .on_conflict_do_nothing(
            constraint="uq_sample_notification_outbox_assignment_recipient"
        )
    )
    return cancel, create
