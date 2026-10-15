"""Restore cleared sample BD fields from matching sent notification evidence."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from erp_api.core.config import get_settings
from erp_api.infrastructure.database import Database
from erp_api.main import build_sample_application_services
from erp_api.models.sample_application import SampleApplication
from erp_api.models.sample_application_event import SampleApplicationEvent
from erp_api.models.sample_application_workflow import SampleApplicationWorkflow
from erp_api.models.sample_ingest_batch import SampleIngestBatch
from erp_api.models.sample_notification_outbox import SampleNotificationOutbox
from erp_api.services.feishu_sample_change import parse_feishu_assignee
from scripts.sample_watch_freshness import SHOPS, TENANT_ID


def _plan_hash(plan: list[dict[str, object]]) -> str:
    body = json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode()).hexdigest()


async def _plan_item(session, shop_id, platform_id: str, *, lock: bool = False):
    statement = (
        select(SampleApplication, SampleApplicationWorkflow)
        .join(
            SampleApplicationWorkflow,
            SampleApplicationWorkflow.sample_application_id == SampleApplication.id,
        )
        .where(
            SampleApplication.tenant_id == TENANT_ID,
            SampleApplication.shop_id == shop_id,
            SampleApplication.platform_application_id == platform_id,
        )
    )
    if lock:
        statement = statement.with_for_update()
    row = (await session.execute(statement)).one_or_none()
    if row is None:
        raise RuntimeError(f"{platform_id}: application_not_found")
    application, workflow = row
    if (
        application.platform_status != "PENDING"
        or not application.is_current_projection
        or application.is_approvable is not True
        or application.approve_expiration_at is None
        or application.approve_expiration_at <= datetime.now(UTC)
        or (application.raw_payload or {}).get("manual_assignment_deleted") is True
    ):
        raise RuntimeError(f"{platform_id}: current_state_not_restorable")
    batch = await session.get(SampleIngestBatch, application.source_capture_id)
    if (
        batch is None
        or batch.status != "complete"
        or batch.finished_at is None
        or (
            batch.expected_total is not None
            and batch.expected_total != batch.captured_total
        )
    ):
        raise RuntimeError(f"{platform_id}: source_batch_incomplete")
    event = await session.scalar(
        select(SampleApplicationEvent)
        .where(
            SampleApplicationEvent.sample_application_id == application.id,
            SampleApplicationEvent.event_source == "erp_auto_assignment",
            SampleApplicationEvent.event_type == "bd_auto_assigned",
        )
        .order_by(SampleApplicationEvent.occurred_at.desc())
        .limit(1)
    )
    if event is None or not isinstance(event.after_data, dict):
        raise RuntimeError(f"{platform_id}: assignment_event_missing")
    bd_name = event.after_data.get("assigned_bd_name")
    rule_version = event.after_data.get("rule_version")
    if not isinstance(bd_name, str) or not bd_name.strip():
        raise RuntimeError(f"{platform_id}: assignment_owner_invalid")
    bd_name = bd_name.strip()
    if workflow.assigned_bd_name not in (None, bd_name):
        raise RuntimeError(f"{platform_id}: assignment_owner_conflict")
    if rule_version != "bd-v17-sample-image-required":
        raise RuntimeError(f"{platform_id}: assignment_rule_not_v17")
    outboxes = (
        await session.scalars(
            select(SampleNotificationOutbox)
            .where(
                SampleNotificationOutbox.sample_application_id == application.id,
                SampleNotificationOutbox.status == "sent",
            )
            .order_by(SampleNotificationOutbox.assignment_version.desc())
        )
    ).all()
    matching = [
        outbox
        for outbox in outboxes
        if (outbox.payload or {}).get("assigned_bd_name") == bd_name
        and (
            outbox.sent_at is not None
            or (outbox.payload or {}).get("message_id")
            or (outbox.payload or {}).get("message_sent_at")
        )
    ]
    if not matching:
        raise RuntimeError(f"{platform_id}: sent_evidence_missing")
    outbox = matching[0]
    return {
        "application_id": str(application.id),
        "platform_application_id": platform_id,
        "bd_name": bd_name,
        "assignment_version": outbox.assignment_version,
        "assigned_at": event.occurred_at.isoformat(),
        "feishu_record_id": workflow.feishu_record_id,
    }


async def _build_plan(database, shop_id, platform_ids, *, lock=False):
    async with database.system_session_factory() as session:
        return [
            await _plan_item(session, shop_id, platform_id, lock=lock)
            for platform_id in platform_ids
        ]


async def _apply(database, shop_id, plan, expected_hash: str) -> None:
    async with database.system_session_factory() as session:
        locked = [
            await _plan_item(
                session, shop_id, str(item["platform_application_id"]), lock=True
            )
            for item in plan
        ]
        if _plan_hash(locked) != expected_hash:
            await session.rollback()
            raise RuntimeError("restore_plan_changed")
        now = datetime.now(UTC)
        for item in locked:
            application_id = UUID(str(item["application_id"]))
            workflow = await session.scalar(
                select(SampleApplicationWorkflow).where(
                    SampleApplicationWorkflow.sample_application_id == application_id
                )
            )
            before = {"assigned_bd_name": workflow.assigned_bd_name}
            workflow.assigned_bd_name = str(item["bd_name"])
            workflow.assignment_version = int(item["assignment_version"])
            workflow.assigned_at = datetime.fromisoformat(str(item["assigned_at"]))
            workflow.processing_status = workflow.processing_status or "待处理"
            await session.execute(
                insert(SampleApplicationEvent)
                .values(
                    tenant_id=TENANT_ID,
                    shop_id=shop_id,
                    sample_application_id=application_id,
                    event_type="bd_assignment_restored",
                    event_source="erp_assignment_repair",
                    external_event_id=(
                        f"restore-sent-evidence:{application_id}:"
                        f"v{item['assignment_version']}"
                    ),
                    actor_id="erp-assignment-repair",
                    actor_name="ERP Assignment Repair",
                    before_data=before,
                    after_data={
                        "assigned_bd_name": item["bd_name"],
                        "rule_version": "bd-v17-sample-image-required",
                        "evidence": "sent_notification",
                    },
                    occurred_at=now,
                )
                .on_conflict_do_nothing(
                    constraint="uq_sample_application_events_tenant_shop_source_external"
                )
            )
        await session.commit()


async def run(shop: str, platform_ids: list[str], apply_hash: str | None) -> None:
    settings = get_settings()
    database = Database(settings.database_url)
    shop_id = SHOPS[shop]
    try:
        plan = await _build_plan(database, shop_id, platform_ids)
        digest = _plan_hash(plan)
        print(json.dumps({"preview_hash": digest, "items": plan}, ensure_ascii=True))
        if apply_hash is None:
            return
        if apply_hash != digest:
            raise RuntimeError("restore_hash_mismatch")
        await _apply(database, shop_id, plan, digest)
        services = build_sample_application_services(settings, database)
        application_ids = frozenset(
            UUID(str(item["application_id"])) for item in plan
        )
        client = services["feishu_sample_client_router"].for_shop(shop_id)
        sample_updates = []
        for item in plan:
            fields = await client.get_record(str(item["feishu_record_id"]))
            if parse_feishu_assignee(fields.get("分配BD")).name != item["bd_name"]:
                sample_updates.append(
                    (str(item["feishu_record_id"]), {"分配BD": item["bd_name"]})
                )
        if sample_updates:
            await client.batch_update_business_fields(sample_updates)
        records = await services["sample_assignment_record_service"].sync(
            tenant_id=TENANT_ID, shop_id=shop_id, application_ids=application_ids
        )
        verified = []
        for item in plan:
            fields = await client.get_record(str(item["feishu_record_id"]))
            if parse_feishu_assignee(fields.get("分配BD")).name != item["bd_name"]:
                raise RuntimeError("feishu_assignment_readback_failed")
            verified.append(item["platform_application_id"])
        async with database.system_session_factory() as session:
            projected_at = datetime.now(UTC)
            workflows = (
                await session.scalars(
                    select(SampleApplicationWorkflow).where(
                        SampleApplicationWorkflow.sample_application_id.in_(
                            application_ids
                        )
                    )
                )
            ).all()
            for workflow in workflows:
                workflow.feishu_updated_at = projected_at
            await session.commit()
        print(
            json.dumps(
                {
                    "status": "verified",
                    "restored": len(verified),
                    "sample_updates": len(sample_updates),
                    "assignment_record_created": records.created_count,
                    "assignment_record_updated": records.updated_count,
                    "notifications_sent": 0,
                }
            )
        )
    finally:
        await database.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("shop", choices=SHOPS)
    parser.add_argument("platform_ids", nargs="+")
    parser.add_argument("--apply-hash")
    arguments = parser.parse_args()
    asyncio.run(run(arguments.shop, arguments.platform_ids, arguments.apply_hash))
