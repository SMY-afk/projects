"""Explicit, journaled single-application daily-BD correction; preview by default."""

import argparse
import asyncio
import json
import logging
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from redis.asyncio import Redis
from sqlalchemy import select

from erp_api.core.config import get_settings
from erp_api.infrastructure.database import Database
from erp_api.models.sample_application import SampleApplication
from erp_api.models.sample_application_event import SampleApplicationEvent
from erp_api.models.sample_application_workflow import SampleApplicationWorkflow
from erp_api.models.sample_ingest_batch import SampleIngestBatch
from erp_api.models.sample_notification_outbox import SampleNotificationOutbox
from erp_api.models.shop import Shop
from erp_api.services.sample_bd_invitation_ai_priority import AiInvitationSnapshotStore
from erp_api.services.sample_business_readiness import SampleBusinessReadiness
from erp_api.services.sample_cooperation_parsing import (
    CHINA_TIMEZONE,
    normalize_account_name,
    plain_text,
)
from erp_api.services.sample_cooperation_records import decision_payload, stored_action
from erp_api.services.sample_cooperation_rules import (
    COOPERATION_ACTIVE_CREATOR_EVENT,
    COOPERATION_EVENT_SOURCE,
    COOPERATION_OWNER_PROTECTED_EVENT,
    CooperationCandidate,
    decide_cooperation,
)
from erp_api.services.sample_cooperation_service import (
    _business_note,
    _processing_result,
)
from erp_api.services.sample_shop_sync_lock import SampleShopSyncLock
from erp_api.services.sample_type_policy import is_assignable_sample
from scripts.sample_watch_freshness import SHOPS, TENANT_ID

REVISION = "daily-bd-read-v1"


def require_current(application, workflow, batch, creator):
    if normalize_account_name(application.creator_username) != normalize_account_name(creator):
        raise RuntimeError("Application creator identity changed")
    if not is_assignable_sample(application, now=datetime.now(UTC)):
        raise RuntimeError("Application is expired, stale, or not currently eligible")
    if (application.raw_payload or {}).get("manual_assignment_deleted") is True:
        raise RuntimeError("Manually deleted assignment cannot be rebuilt")
    if workflow.assigned_bd_name or workflow.assignment_version or workflow.assigned_at:
        raise RuntimeError("An assignment already exists; correction must not recreate it")
    if not workflow.feishu_record_id or batch is None or batch.status != "complete":
        raise RuntimeError("Sample mapping or complete source batch is missing")
    if batch.expected_total is not None and batch.expected_total != batch.captured_total:
        raise RuntimeError("Source batch counts are inconsistent")
    if (batch.completeness_evidence or {}).get("pagination_complete") is not True:
        raise RuntimeError("Source batch pagination is unverified")


async def run(args):
    from erp_api.main import build_sample_application_services
    logging.getLogger("erp_api.feishu_api").setLevel(logging.WARNING)
    settings = get_settings()
    shop_id = SHOPS[args.shop_label]
    database = Database(settings.database_url)
    redis = Redis.from_url(settings.redis_url)
    try:
        async with SampleShopSyncLock(database).acquire(TENANT_ID, shop_id) as acquired:
            if not acquired:
                raise RuntimeError("Shop is busy; do not run beside its active business job")
            await SampleBusinessReadiness().require_ready(tenant_id=TENANT_ID, shop_id=shop_id)
            ai_store = AiInvitationSnapshotStore(redis,
                spreadsheet_token=settings.feishu_ai_invitation_sheet_token,
                sheet_id=settings.feishu_ai_invitation_sheet_id)
            services = build_sample_application_services(settings, database,
                ai_snapshot_store=ai_store)
            precheck = services["sample_cooperation_precheck_service"]
            router = services["feishu_sample_client_router"]
            async with database.system_session_factory() as session:
                application = (await session.scalars(select(SampleApplication).where(
                    SampleApplication.tenant_id == TENANT_ID,
                    SampleApplication.shop_id == shop_id,
                    SampleApplication.platform_application_id == args.application_id))).one()
                workflow = (await session.scalars(select(SampleApplicationWorkflow).where(
                    SampleApplicationWorkflow.tenant_id == TENANT_ID,
                    SampleApplicationWorkflow.sample_application_id == application.id))).one()
                batch = await session.get(SampleIngestBatch, application.source_capture_id)
                shop = await session.get(Shop, shop_id)
                require_current(application, workflow, batch, args.creator)
                events = tuple((await session.scalars(select(SampleApplicationEvent).where(
                    SampleApplicationEvent.tenant_id == TENANT_ID,
                    SampleApplicationEvent.shop_id == shop_id,
                    SampleApplicationEvent.sample_application_id == application.id)
                    .order_by(SampleApplicationEvent.occurred_at))).all())
                outboxes = tuple((await session.scalars(select(SampleNotificationOutbox).where(
                    SampleNotificationOutbox.tenant_id == TENANT_ID,
                    SampleNotificationOutbox.sample_application_id == application.id))).all())
                if any(e.event_type == "bd_auto_assigned" for e in events) or outboxes:
                    raise RuntimeError("Existing assignment or notification evidence requires audit")
            completed_key = f"cooperation-recheck-action:{application.id}:{REVISION}"
            if any(event.external_event_id == completed_key for event in events):
                print("RECHECK_ALREADY_COMPLETED create=0 update=0 notify=0", flush=True)
                return
            creator_id = normalize_account_name(application.creator_username)
            snapshot = await precheck._reader.read(creator_ids=frozenset({creator_id}))
            owners = await precheck._assignment_ownership.read(TENANT_ID, frozenset({creator_id}))
            snapshot = replace(snapshot, assignment_owners=owners)
            candidate = CooperationCandidate(application.id, application.platform_application_id,
                application.creator_username, shop.shop_name,
                application.tiktok_applied_at or application.first_seen_at)
            now = datetime.now(UTC)
            decision = decide_cooperation(candidate, snapshot,
                today=now.astimezone(CHINA_TIMEZONE).date(), now=now)
            allowed_events = {COOPERATION_ACTIVE_CREATOR_EVENT, COOPERATION_OWNER_PROTECTED_EVENT}
            if decision.event_type not in allowed_events or len(decision.recipients) != 1:
                raise RuntimeError(f"Recheck remains blocked: {decision.reason}")
            recipient = decision.recipients[0]
            if recipient.name != args.expected_bd:
                raise RuntimeError("Verified owner differs from approved expected BD")
            if any(recipient.open_id == r.get("open_id")
                   for event in events for r in (event.after_data or {}).get("recipients", [])):
                raise RuntimeError("Prior notice to this BD requires credential reconciliation")
            client = router.for_shop(shop_id)
            fields = await client.get_record(workflow.feishu_record_id)
            if normalize_account_name(fields.get("达人账号")) != creator_id:
                raise RuntimeError("Feishu sample creator does not match the application")
            if application.platform_application_id not in plain_text(fields.get("申请编号")):
                raise RuntimeError("Feishu sample application identity does not match")
            print("RECHECK_PREVIEW " + json.dumps({
                "application": application.platform_application_id,
                "creator": creator_id, "event": decision.event_type,
                "reason": decision.reason, "owner": recipient.name,
                "cooperation_rows": len(snapshot.rows),
                "daily_rows": len(snapshot.daily_valid_rows),
                "allocation_create": 0, "notice_channels": ["original_bd_private"],
            }, ensure_ascii=True), flush=True)
            if not args.apply:
                return
            # Persist the new conclusion before any external action; never delete history.
            event_key = f"cooperation-recheck:{application.id}:{REVISION}"
            event = next((e for e in events if e.external_event_id == event_key), None)
            payload = decision_payload(decision)
            payload["recheck_revision"] = REVISION
            if event is not None:
                if event.after_data != payload:
                    raise RuntimeError("Persisted recheck conclusion changed")
                if datetime.now(UTC) - event.occurred_at > timedelta(hours=23):
                    raise RuntimeError("Old incomplete notice needs delivery credential audit")
            async with database.system_session_factory() as session:
                current = await session.get(SampleApplication, application.id)
                current_workflow = await session.get(SampleApplicationWorkflow, workflow.id,
                    with_for_update=True)
                require_current(current, current_workflow, batch, args.creator)
                if event is None:
                    old = next((e for e in reversed(events)
                        if e.event_type == "sample_cooperation_exception"), None)
                    event = SampleApplicationEvent(id=uuid4(), tenant_id=TENANT_ID,
                        shop_id=shop_id, sample_application_id=application.id,
                        event_type=decision.event_type, event_source=COOPERATION_EVENT_SOURCE,
                        external_event_id=event_key, actor_id="erp-targeted-cooperation-recheck",
                        actor_name="ERP Targeted Cooperation Recheck",
                        before_data=old.after_data if old else None,
                        after_data=payload, occurred_at=datetime.now(UTC))
                    session.add(event)
                await session.commit()
            action = stored_action(event, application, workflow, shop.shop_name)
            message_ids = await precheck._complete_action(action)
            if len(message_ids) != 1:
                raise RuntimeError("Expected exactly one original-BD notification receipt")
            async with database.system_session_factory() as session:
                current_workflow = await session.get(SampleApplicationWorkflow, workflow.id,
                    with_for_update=True)
                current_workflow.processing_result = _processing_result(action)
                current_workflow.business_note = _business_note(action)
                session.add(SampleApplicationEvent(id=uuid4(), tenant_id=TENANT_ID,
                    shop_id=shop_id, sample_application_id=application.id,
                    event_type="sample_cooperation_action_completed",
                    event_source=COOPERATION_EVENT_SOURCE,
                    external_event_id=completed_key, actor_id="erp-targeted-cooperation-recheck",
                    actor_name="ERP Targeted Cooperation Recheck",
                    after_data={"message_ids": list(message_ids),
                        "decision_event_id": str(event.id), "recipient_name": recipient.name,
                        "recheck_revision": REVISION}, occurred_at=datetime.now(UTC)))
                await session.commit()
            readback = await client.get_record(workflow.feishu_record_id)
            if (plain_text(readback.get("处理结果")) != _processing_result(action)
                or plain_text(readback.get("备注")) != _business_note(action)):
                raise RuntimeError("Feishu correction readback differs from its preview")
            print("RECHECK_VERIFIED allocation_create=0 notification_receipts=1 diff=0", flush=True)
    finally:
        await redis.aclose()
        await database.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shop-label", choices=tuple(SHOPS), required=True)
    parser.add_argument("--application-id", required=True)
    parser.add_argument("--creator", required=True)
    parser.add_argument("--expected-bd", required=True)
    parser.add_argument("--apply", action="store_true")
    asyncio.run(run(parser.parse_args()))
