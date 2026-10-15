from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select

from erp_api.core.config import get_settings
from erp_api.infrastructure.database import Database
from erp_api.main import build_sample_application_services
from erp_api.models.sample_application import SampleApplication
from erp_api.models.sample_notification_outbox import SampleNotificationOutbox
from erp_api.services.sample_notification_order import (
    sync_assignment_record_and_deliver,
)


async def _prepare(database, tenant_id, shop_id, platform_application_id):
    statement = (
        select(SampleNotificationOutbox)
        .join(
            SampleApplication,
            SampleApplication.id == SampleNotificationOutbox.sample_application_id,
        )
        .where(
            SampleNotificationOutbox.tenant_id == tenant_id,
            SampleNotificationOutbox.shop_id == shop_id,
            SampleApplication.platform_application_id == platform_application_id,
        )
        .with_for_update()
    )
    async with database.system_session_factory() as session:
        events = (await session.scalars(statement)).all()
        if len(events) != 1:
            raise RuntimeError("Exact notification event is missing or ambiguous.")
        event = events[0]
        payload = event.payload if isinstance(event.payload, dict) else {}
        if payload.get("group_message_id"):
            return event.id, payload["group_message_id"], False
        if event.status != "sent" or not payload.get("message_id"):
            raise RuntimeError("Direct notification evidence is incomplete.")
        event.status = "retry_wait"
        event.next_attempt_at = datetime.now(UTC)
        event.last_error_code = None
        event.last_error_summary = None
        await session.commit()
        return event.id, None, True


async def _readback(database, event_id):
    async with database.system_session_factory() as session:
        event = await session.get(SampleNotificationOutbox, event_id)
        if event is None or not isinstance(event.payload, dict):
            raise RuntimeError("Notification readback is unavailable.")
        return {
            "event_id": str(event.id),
            "status": event.status,
            "message_id": event.payload.get("message_id"),
            "group_message_id": event.payload.get("group_message_id"),
            "group_message_sent_at": event.payload.get("group_message_sent_at"),
            "last_error_code": event.last_error_code,
        }


async def run(arguments) -> None:
    settings = get_settings()
    if not settings.feishu_sample_notification_live_recipients_enabled:
        raise RuntimeError("Live sample notification delivery is disabled.")
    if not settings.feishu_sample_notification_group_chat_id:
        raise RuntimeError("Sample notification group chat is not configured.")
    database = Database(settings.database_url)
    try:
        event_id, existing_group_message_id, prepared = await _prepare(
            database,
            arguments.tenant_id,
            arguments.shop_id,
            arguments.platform_application_id,
        )
        if prepared:
            services = build_sample_application_services(settings, database)
            notifications = services["sample_notification_service"]
            assignment_records = services["sample_assignment_record_service"]
            if notifications is None or assignment_records is None:
                raise RuntimeError("Sample notification services are unavailable.")
            result, _record_result = await sync_assignment_record_and_deliver(
                notifications,
                assignment_records,
                tenant_id=arguments.tenant_id,
                shop_id=arguments.shop_id,
                event_id=event_id,
            )
            if result.status != "sent":
                raise RuntimeError(f"Group notification delivery ended as {result.status}.")
        readback = await _readback(database, event_id)
        if not readback["group_message_id"]:
            raise RuntimeError("Group notification message ID was not persisted.")
        print(
            json.dumps(
                {
                    "already_sent": not prepared,
                    "previous_group_message_id": existing_group_message_id,
                    "readback": readback,
                },
                ensure_ascii=False,
            )
        )
    finally:
        await database.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant-id", type=UUID, required=True)
    parser.add_argument("--shop-id", type=UUID, required=True)
    parser.add_argument("--platform-application-id", required=True)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
