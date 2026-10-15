"""Inspect the latest complete five-shop sample backlog without changing data."""

from __future__ import annotations

import asyncio
import json
from collections import Counter
from datetime import UTC, datetime

from sqlalchemy import and_, or_, select

from erp_api.core.config import get_settings
from erp_api.infrastructure.database import Database
from erp_api.models.sample_application import SampleApplication
from erp_api.models.sample_application_event import SampleApplicationEvent
from erp_api.models.sample_application_workflow import SampleApplicationWorkflow
from erp_api.models.sample_ingest_batch import SampleIngestBatch
from erp_api.models.sample_notification_outbox import SampleNotificationOutbox
from erp_api.services.sample_auto_assignment_repository import (
    SampleAutoAssignmentRepository,
)
from erp_api.services.sample_cooperation_rules import (
    COOPERATION_ALLOWED_EVENT,
    COOPERATION_DECISION_EVENTS,
    COOPERATION_EVENT_SOURCE,
)
from scripts.sample_watch_freshness import SHOPS, TENANT_ID


async def _latest_complete_batch(session, shop_id):
    return await session.scalar(
        select(SampleIngestBatch)
        .where(
            SampleIngestBatch.tenant_id == TENANT_ID,
            SampleIngestBatch.shop_id == shop_id,
            SampleIngestBatch.status == "complete",
            SampleIngestBatch.finished_at.is_not(None),
            or_(
                SampleIngestBatch.expected_total.is_(None),
                SampleIngestBatch.expected_total
                == SampleIngestBatch.captured_total,
            ),
        )
        .order_by(SampleIngestBatch.finished_at.desc())
        .limit(1)
    )


async def _shop_report(session, assignment_repository, label, shop_id):
    batch = await _latest_complete_batch(session, shop_id)
    if batch is None:
        return {"shop": label, "status": "missing_complete_batch"}
    rows = (
        await session.execute(
            select(SampleApplication, SampleApplicationWorkflow)
            .join(
                SampleApplicationWorkflow,
                and_(
                    SampleApplicationWorkflow.sample_application_id
                    == SampleApplication.id,
                    SampleApplicationWorkflow.tenant_id
                    == SampleApplication.tenant_id,
                    SampleApplicationWorkflow.shop_id == SampleApplication.shop_id,
                ),
            )
            .where(
                SampleApplication.tenant_id == TENANT_ID,
                SampleApplication.shop_id == shop_id,
                SampleApplication.source_capture_id == batch.id,
                SampleApplication.platform_status == "PENDING",
                SampleApplication.is_current_projection.is_(True),
                SampleApplication.is_approvable.is_(True),
                SampleApplication.approve_expiration_at > datetime.now(UTC),
            )
            .order_by(
                SampleApplication.approve_expiration_at,
                SampleApplication.tiktok_applied_at,
            )
        )
    ).all()
    ids = [application.id for application, _workflow in rows]
    assignment_pending = await assignment_repository.list_pending(
        TENANT_ID,
        shop_id,
        application_ids=frozenset(ids),
        exclude_previously_blocked=True,
    )
    assignment_pending_ids = {
        pending.application_id for pending in assignment_pending
    }
    events = (
        (
            await session.scalars(
                select(SampleApplicationEvent).where(
                    SampleApplicationEvent.sample_application_id.in_(ids)
                )
            )
        ).all()
        if ids
        else []
    )
    outboxes = (
        (
            await session.scalars(
                select(SampleNotificationOutbox).where(
                    SampleNotificationOutbox.sample_application_id.in_(ids)
                )
            )
        ).all()
        if ids
        else []
    )
    events_by_application = {}
    for event in events:
        events_by_application.setdefault(event.sample_application_id, []).append(event)
    outboxes_by_application = {}
    for outbox in outboxes:
        outboxes_by_application.setdefault(outbox.sample_application_id, []).append(
            outbox
        )

    counts = Counter()
    actionable = []
    outside_scope = []
    for application, workflow in rows:
        app_events = events_by_application.get(application.id, [])
        app_outboxes = outboxes_by_application.get(application.id, [])
        cooperation_events = [
            event
            for event in app_events
            if event.event_source == COOPERATION_EVENT_SOURCE
            and event.event_type in COOPERATION_DECISION_EVENTS
        ]
        has_allowed = any(
            event.event_type == COOPERATION_ALLOWED_EVENT
            for event in cooperation_events
        )
        has_auto_block = any(
            event.event_source == "erp_auto_assignment"
            and event.event_type == "bd_auto_blocked"
            for event in app_events
        )
        has_auto_assignment = any(
            event.event_source == "erp_auto_assignment"
            and event.event_type == "bd_auto_assigned"
            for event in app_events
        )
        has_delivery = any(
            outbox.status == "sent"
            or outbox.sent_at is not None
            or bool((outbox.payload or {}).get("message_id"))
            or bool((outbox.payload or {}).get("message_sent_at"))
            for outbox in app_outboxes
        )
        if workflow.feishu_record_id is None:
            state = "missing_sample_record"
        elif workflow.assigned_bd_name:
            state = "complete" if has_delivery else "notification_due"
        elif has_auto_block:
            state = "blocked_unchanged"
        elif has_allowed:
            state = "assignment_candidate"
        elif cooperation_events:
            state = "cooperation_blocked"
        else:
            state = "cooperation_due"
        if (
            state == "assignment_candidate"
            and application.id not in assignment_pending_ids
        ):
            state = "outside_v17_assignment_scope"
            raw = application.raw_payload or {}
            hints = []
            if raw.get("is_proactive_invitation") is None:
                hints.append("proactive_marker_missing")
            if raw.get("manual_assignment_deleted") is True:
                hints.append("manual_assignment_deleted")
            if has_auto_assignment:
                hints.append("previous_auto_assignment")
            if has_delivery:
                hints.append("existing_notification_evidence")
            if not hints:
                hints.append("group_or_identity_rank_filter")
            outside_scope.append(
                {
                    "platform_application_id": application.platform_application_id,
                    "creator_username": application.creator_username,
                    "expires_at": application.approve_expiration_at.isoformat(),
                    "hints": hints,
                    "event_bd_names": sorted(
                        {
                            str((event.after_data or {}).get("assigned_bd_name"))
                            for event in app_events
                            if event.event_source == "erp_auto_assignment"
                            and event.event_type == "bd_auto_assigned"
                            and (event.after_data or {}).get("assigned_bd_name")
                        }
                    ),
                    "outbox_bd_names": sorted(
                        {
                            str((outbox.payload or {}).get("assigned_bd_name"))
                            for outbox in app_outboxes
                            if (outbox.payload or {}).get("assigned_bd_name")
                        }
                    ),
                    "outbox_statuses": sorted(
                        {outbox.status for outbox in app_outboxes}
                    ),
                }
            )
        counts[state] += 1
        if state in {
            "missing_sample_record",
            "cooperation_due",
            "assignment_candidate",
            "notification_due",
        }:
            actionable.append(
                {
                    "platform_application_id": application.platform_application_id,
                    "creator_username": application.creator_username,
                    "expires_at": application.approve_expiration_at.isoformat(),
                    "state": state,
                }
            )
    return {
        "shop": label,
        "status": "ok",
        "batch_finished_at": batch.finished_at.isoformat(),
        "batch_captured_total": batch.captured_total,
        "current_unexpired": len(rows),
        "v17_assignment_pending": len(assignment_pending_ids),
        "counts": dict(sorted(counts.items())),
        "actionable_count": len(actionable),
        "actionable_preview": actionable[:10],
        "outside_v17_preview": outside_scope[:10],
    }


async def main() -> None:
    settings = get_settings()
    database = Database(settings.database_url)
    assignment_repository = SampleAutoAssignmentRepository(
        database,
        category=settings.feishu_sample_auto_assignment_category,
        batch_limit=settings.feishu_sample_auto_assignment_batch_limit,
        activation_at=settings.feishu_sample_auto_assignment_activation_at,
    )
    try:
        async with database.system_session_factory() as session:
            for label, shop_id in SHOPS.items():
                report = await _shop_report(
                    session, assignment_repository, label, shop_id
                )
                print(json.dumps(report, ensure_ascii=False), flush=True)
    finally:
        await database.dispose()


if __name__ == "__main__":
    asyncio.run(main())
