"""Replay explicitly audited sample applications, one verified item at a time."""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import select

from erp_api.core.config import get_settings
from erp_api.infrastructure.database import Database
from erp_api.main import build_sample_application_services
from erp_api.models.sample_application import SampleApplication
from erp_api.models.sample_application_event import SampleApplicationEvent
from erp_api.models.sample_application_workflow import SampleApplicationWorkflow
from erp_api.models.sample_ingest_batch import SampleIngestBatch
from erp_api.models.sample_notification_outbox import SampleNotificationOutbox
from erp_api.services.sample_cooperation_repository import SampleCooperationRepository
from erp_api.services.sample_notification_repository import SampleNotificationRepository
from scripts.sample_watch_freshness import SHOPS, TENANT_ID


async def _eligible(
    database: Database,
    shop_id,
    platform_id: str,
    *,
    allow_existing_sample_record: bool,
):
    async with database.system_session_factory() as session:
        application = await session.scalar(
            select(SampleApplication).where(
                SampleApplication.tenant_id == TENANT_ID,
                SampleApplication.shop_id == shop_id,
                SampleApplication.platform_application_id == platform_id,
            )
        )
        if application is None:
            return None, "missing_application"
        if (
            application.platform_status != "PENDING"
            or application.is_current_projection is not True
            or application.is_approvable is not True
            or application.approve_expiration_at is None
            or application.approve_expiration_at <= datetime.now(UTC)
        ):
            return None, "not_current_or_expired"
        batch = (
            await session.get(SampleIngestBatch, application.source_capture_id)
            if application.source_capture_id
            else None
        )
        if (
            application.source_type != "hubstudio_cdp"
            or batch is None
            or batch.status != "complete"
            or batch.finished_at is None
            or (
                batch.expected_total is not None
                and batch.expected_total != batch.captured_total
            )
        ):
            return None, "source_batch_incomplete"
        workflow = await session.scalar(
            select(SampleApplicationWorkflow).where(
                SampleApplicationWorkflow.sample_application_id == application.id
            )
        )
        if workflow is None:
            return None, "workflow_missing"
        if workflow.assigned_bd_name:
            return None, "existing_assignment"
        if workflow.feishu_record_id and not allow_existing_sample_record:
            return None, "existing_sample_record"
        outbox = await session.scalar(
            select(SampleNotificationOutbox.id)
            .where(SampleNotificationOutbox.sample_application_id == application.id)
            .limit(1)
        )
        if outbox:
            return None, "existing_notification_evidence"
        blocked = await session.scalar(
            select(SampleApplicationEvent.id)
            .where(
                SampleApplicationEvent.sample_application_id == application.id,
                SampleApplicationEvent.event_type == "bd_auto_blocked",
            )
            .limit(1)
        )
        if blocked:
            return None, "already_blocked_unchanged"
        if not (application.creator_open_id and application.product_id and application.sku_id):
            return None, "required_field_missing"
        return application, None


async def _assert_no_other_due(database: Database, settings, shop_id) -> None:
    cooperation = SampleCooperationRepository(
        database,
        activation_at=settings.feishu_sample_auto_assignment_activation_at,
        batch_limit=settings.feishu_sample_auto_assignment_batch_limit,
    )
    notifications = SampleNotificationRepository(database)
    if await cooperation.list_due_actions(TENANT_ID, shop_id):
        raise RuntimeError("unrelated_cooperation_action_due")
    if await notifications.list_due(
        now=datetime.now(UTC),
        processing_timeout=timedelta(minutes=10),
        tenant_id=TENANT_ID,
        shop_id=shop_id,
    ):
        raise RuntimeError("unrelated_notification_due")


async def _readback(database: Database, application_id) -> tuple[bool, bool, str, str]:
    async with database.system_session_factory() as session:
        workflow = await session.scalar(
            select(SampleApplicationWorkflow).where(
                SampleApplicationWorkflow.sample_application_id == application_id
            )
        )
        outboxes = (
            await session.scalars(
                select(SampleNotificationOutbox).where(
                    SampleNotificationOutbox.sample_application_id == application_id
                )
            )
        ).all()
        blocked = await session.scalar(
            select(SampleApplicationEvent).where(
                SampleApplicationEvent.sample_application_id == application_id,
                SampleApplicationEvent.event_type == "bd_auto_blocked",
            )
        )
        reason = (blocked.after_data or {}).get("blocked_reason") if blocked else ""
        evidence = "none"
        if outboxes:
            evidence = ",".join(
                f"{item.status}:{bool(item.sent_at)}:"
                f"{bool(item.payload.get('message_id'))}:"
                f"{bool(item.payload.get('group_message_id'))}"
                for item in outboxes
            )
        return (
            bool(workflow and workflow.feishu_record_id),
            bool(workflow and workflow.assigned_bd_name),
            evidence,
            str(reason or ""),
        )


async def run(
    shop: str,
    platform_ids: list[str],
    *,
    allow_existing_sample_record: bool,
) -> None:
    if shop not in SHOPS or len(platform_ids) != len(set(platform_ids)):
        raise ValueError("Shop or platform application ids are invalid.")
    settings = get_settings()
    database = Database(settings.database_url)
    try:
        pipeline = build_sample_application_services(settings, database)[
            "sample_shop_pipeline_service"
        ]
        if pipeline is None:
            raise RuntimeError("Sample pipeline is unavailable.")
        for platform_id in platform_ids:
            application, reason = await _eligible(
                database,
                SHOPS[shop],
                platform_id,
                allow_existing_sample_record=allow_existing_sample_record,
            )
            if reason:
                print(f"{platform_id} skipped {reason}", flush=True)
                continue
            await _assert_no_other_due(database, settings, SHOPS[shop])
            print(f"{platform_id} processing", flush=True)
            result = await pipeline.complete_after_source(
                tenant_id=TENANT_ID,
                shop_id=SHOPS[shop],
                source_type="hubstudio_cdp",
                source_results=(
                    SimpleNamespace(
                        application_ids=frozenset({application.id}),
                        obsolete_platform_application_ids=frozenset(),
                    ),
                ),
            )
            feishu, assigned, evidence, blocked = await _readback(
                database, application.id
            )
            print(
                f"{platform_id} result={result.status} feishu={feishu} "
                f"assigned={assigned} notification={evidence} blocked={blocked}",
                flush=True,
            )
            if not feishu or (assigned and not evidence.startswith("sent:True:True:True")):
                raise RuntimeError(f"{platform_id} readback incomplete; stopped")
    finally:
        await database.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("shop", choices=SHOPS)
    parser.add_argument("platform_ids", nargs="+")
    parser.add_argument("--allow-existing-sample-record", action="store_true")
    arguments = parser.parse_args()
    asyncio.run(
        run(
            arguments.shop,
            arguments.platform_ids,
            allow_existing_sample_record=arguments.allow_existing_sample_record,
        )
    )
