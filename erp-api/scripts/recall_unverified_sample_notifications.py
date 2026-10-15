from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from erp_api.core.config import get_settings
from erp_api.infrastructure.database import Database
from erp_api.models.sample_application import SampleApplication
from erp_api.models.sample_application_event import SampleApplicationEvent
from erp_api.models.sample_notification_outbox import SampleNotificationOutbox
from erp_api.services.feishu_notification_client import FeishuNotificationClient
from erp_api.services.feishu_sample_batch_client import FeishuSampleBatchClient


async def main() -> None:
    args = _arguments()
    settings = get_settings()
    database = Database(settings.database_url)
    try:
        targets = await _load_targets(database, args.outbox_id)
        summary = {
            "target_count": len(targets),
            "sent_count": sum(target.status == "sent" for target, _ in targets),
            "message_count": sum(len(_message_ids(target)) for target, _ in targets),
            "apply": args.apply,
        }
        print(json.dumps(summary, ensure_ascii=False))
        if not args.apply:
            return
        client = _notification_client(settings)
        for target, application in targets:
            for message_id in _message_ids(target):
                await client.delete_message(message_id=message_id)
            await _cancel_target(database, target, application)
    finally:
        await database.dispose()


async def _load_targets(database: Database, ids: list[UUID]):
    async with database.system_session_factory() as session:
        rows = (
            await session.execute(
                select(SampleNotificationOutbox, SampleApplication)
                .join(
                    SampleApplication,
                    SampleApplication.id
                    == SampleNotificationOutbox.sample_application_id,
                )
                .where(SampleNotificationOutbox.id.in_(ids))
                .order_by(SampleNotificationOutbox.created_at)
            )
        ).all()
    if len(rows) != len(set(ids)):
        raise RuntimeError("One or more notification targets were not found.")
    for outbox, application in rows:
        if outbox.status not in {"sent", "failed"}:
            raise RuntimeError("Only sent or failed notifications can be remediated.")
        raw_payload = application.raw_payload
        if (
            isinstance(raw_payload, dict)
            and raw_payload.get("is_proactive_invitation") is False
        ):
            raise RuntimeError("Verified organic notifications cannot be remediated.")
    return rows


def _message_ids(outbox: SampleNotificationOutbox) -> tuple[str, ...]:
    payload = outbox.payload if isinstance(outbox.payload, dict) else {}
    result = []
    for key in ("message_id", "group_message_id"):
        value = payload.get(key)
        if isinstance(value, str) and value and value not in result:
            result.append(value)
    return tuple(result)


async def _cancel_target(
    database: Database,
    target: SampleNotificationOutbox,
    application: SampleApplication,
) -> None:
    now = datetime.now(UTC)
    async with database.system_session_factory() as session:
        outbox = await session.get(
            SampleNotificationOutbox, target.id, with_for_update=True
        )
        if outbox is None or outbox.status not in {"sent", "failed"}:
            raise RuntimeError("Notification state changed during remediation.")
        previous_status = outbox.status
        marker = (
            application.raw_payload.get("is_proactive_invitation")
            if isinstance(application.raw_payload, dict)
            else None
        )
        reason = (
            "proactive_invitation_excluded"
            if marker is True
            else "organic_source_unverified"
        )
        outbox.status = "cancelled"
        outbox.next_attempt_at = None
        outbox.last_error_code = reason
        outbox.last_error_summary = (
            "Notification recalled or cancelled by the organic-source safety gate."
        )
        await session.execute(
            insert(SampleApplicationEvent)
            .values(
                id=uuid4(),
                tenant_id=outbox.tenant_id,
                shop_id=outbox.shop_id,
                sample_application_id=outbox.sample_application_id,
                event_type=(
                    "notification_recalled"
                    if previous_status == "sent"
                    else "notification_cancelled"
                ),
                event_source="erp_notification_safety_gate",
                external_event_id=f"organic-gate:{outbox.id}",
                actor_id="erp-notification-safety-gate",
                actor_name="ERP Notification Safety Gate",
                before_data={"status": previous_status},
                after_data={"status": "cancelled", "reason": reason},
                occurred_at=now,
            )
            .on_conflict_do_nothing(
                constraint=("uq_sample_application_events_tenant_shop_source_external")
            )
        )
        await session.commit()


def _notification_client(settings) -> FeishuNotificationClient:
    if not (
        settings.feishu_app_id
        and settings.feishu_app_secret
        and settings.feishu_sample_base_token
        and settings.feishu_sample_table_id
    ):
        raise RuntimeError("Feishu notification settings are incomplete.")
    sample_client = FeishuSampleBatchClient(
        app_id=settings.feishu_app_id,
        app_secret=settings.feishu_app_secret.get_secret_value(),
        base_token=settings.feishu_sample_base_token.get_secret_value(),
        table_id=settings.feishu_sample_table_id,
    )
    return FeishuNotificationClient(sample_client)


def _arguments():
    parser = argparse.ArgumentParser(
        description="Recall or cancel sample notifications lacking organic evidence."
    )
    parser.add_argument("--outbox-id", action="append", type=UUID, required=True)
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(main())
