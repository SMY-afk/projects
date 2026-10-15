from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from erp_api.core.config import get_settings
from erp_api.infrastructure.database import Database
from erp_api.models.sample_application import SampleApplication
from erp_api.models.sample_application_event import SampleApplicationEvent
from erp_api.models.sample_application_workflow import SampleApplicationWorkflow
from erp_api.models.sample_notification_outbox import SampleNotificationOutbox
from erp_api.models.shop import Shop
from erp_api.services.feishu_assignment_record_client import (
    FeishuAssignmentRecordClient,
)
from erp_api.services.feishu_notification_client import FeishuNotificationClient
from erp_api.services.feishu_sample_batch_client import FeishuSampleBatchClient
from erp_api.services.sample_assignment_removal import (
    AssignmentRemovalTarget,
    suppress_sample_assignments,
)
from erp_api.services.sample_feishu_client_router import SampleFeishuClientRouter


@dataclass(frozen=True)
class Target:
    application: SampleApplication
    workflow: SampleApplicationWorkflow
    outbox: SampleNotificationOutbox
    shop: Shop


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--application-id", action="append", type=UUID, required=True)
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args()


async def _load_targets(database: Database, ids: list[UUID]) -> tuple[Target, ...]:
    statement = (
        select(
            SampleApplication,
            SampleApplicationWorkflow,
            SampleNotificationOutbox,
            Shop,
        )
        .join(
            SampleApplicationWorkflow,
            SampleApplicationWorkflow.sample_application_id == SampleApplication.id,
        )
        .join(
            SampleNotificationOutbox,
            (SampleNotificationOutbox.sample_application_id == SampleApplication.id)
            & (
                SampleNotificationOutbox.assignment_version
                == SampleApplicationWorkflow.assignment_version
            ),
        )
        .join(Shop, Shop.id == SampleApplication.shop_id)
        .where(SampleApplication.id.in_(ids))
        .order_by(SampleApplication.created_at)
    )
    async with database.system_session_factory() as session:
        rows = tuple((await session.execute(statement)).all())
    if len(rows) != len(set(ids)):
        raise RuntimeError("Every application must have one current assignment outbox.")
    targets = tuple(Target(*row) for row in rows)
    for target in targets:
        if not target.workflow.assigned_bd_name or not target.workflow.feishu_record_id:
            raise RuntimeError("A target does not have an active assignment.")
        if target.outbox.status not in {"sent", "failed"}:
            raise RuntimeError("Assignment notification status is not removable.")
        if target.outbox.status == "failed" and _message_ids(target.outbox):
            raise RuntimeError("Failed notification has message IDs; inspect manually.")
    return targets


async def _load_assignment_records(client, targets: tuple[Target, ...]):
    creators = {
        (target.application.creator_username or "").strip().lstrip("@").casefold()
        for target in targets
    }
    outbox_ids = {str(target.outbox.id) for target in targets}
    matches = []
    for record in await client.list_record_snapshots():
        fields = record.snapshot.fields
        creator = str(fields.get("达人ID") or "").strip().lstrip("@").casefold()
        if creator not in creators:
            continue
        assignment_number = str(fields.get("分配编号") or "").strip()
        if assignment_number not in outbox_ids:
            raise RuntimeError(
                f"Creator {creator} has an unselected assignment record."
            )
        matches.append(record)
    matched_creators = {
        str(record.snapshot.fields.get("达人ID") or "")
        .strip()
        .lstrip("@")
        .casefold()
        for record in matches
    }
    if creators != matched_creators:
        raise RuntimeError("Each selected creator must have a Feishu assignment record.")
    record_ids = {record.record_id for record in matches}
    for target in targets:
        expected_id = (target.outbox.payload or {}).get("assignment_record_id")
        if expected_id and expected_id not in record_ids:
            raise RuntimeError("Outbox assignment record ID does not match Feishu.")
    return tuple(matches)


def _message_ids(outbox: SampleNotificationOutbox) -> tuple[str, ...]:
    payload = outbox.payload if isinstance(outbox.payload, dict) else {}
    return tuple(
        value
        for key in ("message_id", "group_message_id")
        if isinstance((value := payload.get(key)), str) and value
    )


async def _record_notification_recalls(
    database: Database, targets: tuple[Target, ...]
) -> None:
    targets = tuple(target for target in targets if _message_ids(target.outbox))
    if not targets:
        return
    now = datetime.now(UTC)
    async with database.system_session_factory() as session:
        for target in targets:
            await session.execute(
                insert(SampleApplicationEvent)
                .values(
                    id=uuid4(),
                    tenant_id=target.application.tenant_id,
                    shop_id=target.application.shop_id,
                    sample_application_id=target.application.id,
                    event_type="notification_recalled",
                    event_source="manual_user_request",
                    external_event_id=f"notification-recall:{target.outbox.id}",
                    actor_id="codex-user-request",
                    actor_name="User approved in Codex",
                    before_data={
                        "status": target.outbox.status,
                        "message_ids": _message_ids(target.outbox),
                    },
                    after_data={"status": "cancelled", "reason": "assignment_removed"},
                    occurred_at=now,
                )
                .on_conflict_do_nothing(
                    constraint="uq_sample_application_events_tenant_shop_source_external"
                )
            )
        await session.commit()


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


def _notification_client(settings) -> FeishuNotificationClient:
    return FeishuNotificationClient(_source_router(settings)._default)


async def main() -> None:
    args = _arguments()
    settings = get_settings()
    database = Database(settings.database_url)
    try:
        targets = await _load_targets(database, args.application_id)
        assignment_client = _assignment_client(settings)
        records = await _load_assignment_records(assignment_client, targets)
        report = {
            "apply": args.apply,
            "applications": [
                {
                    "id": str(target.application.id),
                    "creator": target.application.creator_username,
                    "shop": target.shop.shop_name,
                    "bd": target.workflow.assigned_bd_name,
                    "outbox": str(target.outbox.id),
                    "messages": _message_ids(target.outbox),
                }
                for target in targets
            ],
            "assignment_record_ids": [record.record_id for record in records],
        }
        print(json.dumps(report, ensure_ascii=True))
        if not args.apply:
            return
        record_by_number = {
            str(record.snapshot.fields.get("分配编号") or ""): record.record_id
            for record in records
        }
        removals = tuple(
            AssignmentRemovalTarget(
                creator=target.application.creator_username or "",
                application_id=target.application.id,
                platform_application_id=target.application.platform_application_id,
                shop_id=target.application.shop_id,
                shop_name=target.shop.shop_name,
                source_record_id=target.workflow.feishu_record_id or "",
                assigned_bd_name=target.workflow.assigned_bd_name or "",
                assignment_version=target.workflow.assignment_version,
                outbox_id=target.outbox.id,
                outbox_status=target.outbox.status,
                assignment_record_id=record_by_number.get(str(target.outbox.id), ""),
            )
            for target in targets
        )
        await suppress_sample_assignments(database, removals)
        source_router = _source_router(settings)
        for target in targets:
            await source_router.for_shop(target.application.shop_id).update_business_fields(
                target.workflow.feishu_record_id, {"分配BD": None}
            )
        for record in records:
            await assignment_client.delete_assignment_record(record.record_id)
        notification_client = _notification_client(settings)
        for target in targets:
            for message_id in _message_ids(target.outbox):
                await notification_client.delete_message(message_id=message_id)
        await _record_notification_recalls(database, targets)
        print(json.dumps({"status": "removed", "count": len(targets)}))
    finally:
        await database.dispose()


if __name__ == "__main__":
    asyncio.run(main())
