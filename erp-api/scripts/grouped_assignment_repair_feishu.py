from __future__ import annotations

from collections import defaultdict
from uuid import UUID

from sqlalchemy import select

from erp_api.infrastructure.database import Database
from erp_api.models.sample_application import SampleApplication
from erp_api.models.sample_application_workflow import SampleApplicationWorkflow
from erp_api.models.sample_notification_outbox import SampleNotificationOutbox
from erp_api.models.shop import Shop
from erp_api.services.feishu_assignment_record_client import (
    FeishuAssignmentRecordClient,
)
from erp_api.services.feishu_sample_batch_client import FeishuSampleBatchClient
from erp_api.services.sample_assignment_record_fields import record_fields
from erp_api.services.sample_feishu_client_router import SampleFeishuClientRouter

ASSIGNMENT_NUMBER = "\u5206\u914d\u7f16\u53f7"
APPLICATION_NUMBER = "\u7533\u8bf7\u7f16\u53f7"
NOTIFICATION_STATUS = "\u901a\u77e5\u72b6\u6001"
CANCELLED = "\u5df2\u53d6\u6d88"
ASSIGNED_BD = "\u5206\u914dBD"
PROCESSING_STATUS = "\u5904\u7406\u72b6\u6001"


def _assignment_client(settings) -> FeishuAssignmentRecordClient:
    return FeishuAssignmentRecordClient(
        app_id=settings.feishu_app_id,
        app_secret=settings.feishu_app_secret.get_secret_value(),
        base_token=settings.feishu_sample_base_token.get_secret_value(),
        table_id=settings.feishu_bd_assignment_record_table_id,
    )


def _source_router(settings) -> SampleFeishuClientRouter:
    options = {
        "app_id": settings.feishu_app_id,
        "app_secret": settings.feishu_app_secret.get_secret_value(),
        "base_token": settings.feishu_sample_base_token.get_secret_value(),
    }
    default = FeishuSampleBatchClient(
        **options, table_id=settings.feishu_sample_table_id
    )
    clients = {
        shop_id: FeishuSampleBatchClient(**options, table_id=table_id)
        for shop_id, table_id in settings.feishu_sample_shop_table_ids.items()
    }
    return SampleFeishuClientRouter(default, clients)


async def canonical_targets(database: Database, application_ids: set[UUID]):
    statement = (
        select(
            SampleNotificationOutbox,
            SampleApplication,
            SampleApplicationWorkflow,
            Shop,
        )
        .join(
            SampleApplication,
            SampleApplication.id == SampleNotificationOutbox.sample_application_id,
        )
        .join(
            SampleApplicationWorkflow,
            SampleApplicationWorkflow.sample_application_id == SampleApplication.id,
        )
        .join(Shop, Shop.id == SampleApplication.shop_id)
        .where(
            SampleApplication.id.in_(application_ids),
            SampleApplication.is_current_projection.is_(True),
            SampleNotificationOutbox.status != "cancelled",
            SampleNotificationOutbox.assignment_version
            == SampleApplicationWorkflow.assignment_version,
        )
    )
    async with database.system_session_factory() as session:
        rows = tuple((await session.execute(statement)).all())
    if len(rows) != len(application_ids):
        raise RuntimeError("Every current application must have one canonical outbox.")
    return rows


async def repair_feishu(
    settings,
    targets,
    *,
    save_outbox_id: UUID,
    hey_assignment_number: str,
) -> dict[str, object]:
    assignment_client = _assignment_client(settings)
    source_router = _source_router(settings)
    snapshots = await assignment_client.list_record_snapshots()
    by_number = defaultdict(list)
    for snapshot in snapshots:
        number = snapshot.snapshot.fields.get(ASSIGNMENT_NUMBER)
        if isinstance(number, str):
            by_number[number].append(snapshot)
    cancellation_numbers = (str(save_outbox_id), hey_assignment_number)
    for number in cancellation_numbers:
        if len(by_number[number]) != 1:
            raise RuntimeError(f"Assignment row {number} is not unique.")

    updated = []
    for row in targets:
        outbox, application, workflow, _shop = row
        payload = outbox.payload if isinstance(outbox.payload, dict) else {}
        record_id = payload.get("assignment_record_id")
        if not isinstance(record_id, str) or not record_id:
            raise RuntimeError(f"Outbox {outbox.id} has no persistent record_id.")
        fields = record_fields(row)
        await assignment_client.update_assignment_record(record_id, fields)
        await source_router.for_shop(application.shop_id).update_business_fields(
            workflow.feishu_record_id,
            {
                ASSIGNED_BD: workflow.assigned_bd_name,
                PROCESSING_STATUS: workflow.processing_status,
            },
        )
        updated.append((record_id, fields[APPLICATION_NUMBER]))
    for number in cancellation_numbers:
        await assignment_client.update_assignment_record(
            by_number[number][0].record_id,
            {NOTIFICATION_STATUS: CANCELLED},
        )

    refreshed = {
        item.record_id: item.snapshot.fields
        for item in await assignment_client.list_record_snapshots()
    }
    mismatches = []
    for record_id, application_number in updated:
        if refreshed.get(record_id, {}).get(APPLICATION_NUMBER) != application_number:
            mismatches.append(record_id)
    for number in cancellation_numbers:
        record_id = by_number[number][0].record_id
        if refreshed.get(record_id, {}).get(NOTIFICATION_STATUS) != CANCELLED:
            mismatches.append(record_id)
    if mismatches:
        raise RuntimeError(f"Feishu readback mismatch: {mismatches}")
    return {
        "updated_assignment_rows": len(updated),
        "cancelled_assignment_rows": len(cancellation_numbers),
        "readback_mismatches": 0,
    }


async def application_id_for_outbox(database: Database, outbox_id: UUID) -> UUID:
    async with database.system_session_factory() as session:
        value = await session.scalar(
            select(SampleNotificationOutbox.sample_application_id).where(
                SampleNotificationOutbox.id == outbox_id
            )
        )
    if value is None:
        raise RuntimeError("The assignment application is unavailable.")
    return value
