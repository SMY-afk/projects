from __future__ import annotations

import argparse
import asyncio
import json
from uuid import UUID

from sqlalchemy import and_, select

from erp_api.core.config import get_settings
from erp_api.infrastructure.database import Database
from erp_api.models.sample_application import SampleApplication
from erp_api.models.sample_notification_outbox import SampleNotificationOutbox
from erp_api.models.shop import Shop
from erp_api.services.feishu_assignment_record_client import (
    FeishuAssignmentRecordClient,
)
from erp_api.services.sample_assignment_record_service import (
    SampleAssignmentRecordService,
)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    if not (
        settings.feishu_app_id
        and settings.feishu_app_secret
        and settings.feishu_sample_base_token
        and settings.feishu_bd_assignment_record_table_id
        and settings.feishu_sample_auto_assignment_activation_at
    ):
        raise RuntimeError("Feishu assignment record backfill is not configured.")
    database = Database(settings.database_url)
    try:
        scopes = await _assignment_scopes(database)
        print(
            json.dumps(
                {"status": "ready", "shop_count": len(scopes), "apply": args.apply}
            )
        )
        if not args.apply:
            return
        client = FeishuAssignmentRecordClient(
            app_id=settings.feishu_app_id,
            app_secret=settings.feishu_app_secret.get_secret_value(),
            base_token=settings.feishu_sample_base_token.get_secret_value(),
            table_id=settings.feishu_bd_assignment_record_table_id,
        )
        service = SampleAssignmentRecordService(
            database,
            client,
            activation_at=settings.feishu_sample_auto_assignment_activation_at,
            limit=100,
        )
        created = updated = 0
        for tenant_id, shop_id in scopes:
            result = await service.sync(tenant_id=tenant_id, shop_id=shop_id)
            created += result.created_count
            updated += result.updated_count
        identity_updated_count, identity_verified_count = (
            await _backfill_record_identities(database, client)
        )
        verified_count = await _verify_assignment_records(service, client, scopes)
        print(
            json.dumps(
                {
                    "status": "updated",
                    "shop_count": len(scopes),
                    "created_count": created,
                    "updated_count": updated,
                    "identity_updated_count": identity_updated_count,
                    "identity_verified_count": identity_verified_count,
                    "verified_count": verified_count,
                }
            )
        )
    finally:
        await database.dispose()


async def _assignment_scopes(database: Database):
    statement = (
        select(
            SampleNotificationOutbox.tenant_id,
            SampleNotificationOutbox.shop_id,
        )
        .where(
            SampleNotificationOutbox.payload["source_event_id"].astext.like(
                "bd-auto:%"
            )
        )
        .distinct()
        .order_by(
            SampleNotificationOutbox.tenant_id,
            SampleNotificationOutbox.shop_id,
        )
    )
    async with database.system_session_factory() as session:
        return tuple((await session.execute(statement)).all())


async def _backfill_record_identities(database: Database, client) -> tuple[int, int]:
    records = await client.list_record_snapshots()
    records_by_outbox_id = {}
    for record in records:
        number = record.snapshot.fields.get("分配编号")
        if not isinstance(number, str) or not number.strip():
            continue
        try:
            outbox_id = UUID(number.strip())
        except ValueError:
            continue
        if outbox_id in records_by_outbox_id:
            raise RuntimeError("Feishu assignment record identity is duplicated.")
        records_by_outbox_id[outbox_id] = record
    if not records_by_outbox_id:
        return 0, 0
    statement = (
        select(
            SampleNotificationOutbox.id,
            SampleApplication.creator_username,
            Shop.shop_name,
        )
        .join(
            SampleApplication,
            SampleApplication.id == SampleNotificationOutbox.sample_application_id,
        )
        .join(
            Shop,
            and_(
                Shop.id == SampleApplication.shop_id,
                Shop.tenant_id == SampleApplication.tenant_id,
            ),
        )
        .where(SampleNotificationOutbox.id.in_(records_by_outbox_id))
    )
    async with database.system_session_factory() as session:
        targets = tuple((await session.execute(statement)).all())
    updated_count = 0
    for outbox_id, creator_username, shop_name in targets:
        record = records_by_outbox_id[outbox_id]
        expected = {
            "达人ID": creator_username or "",
            "店铺名称": shop_name,
        }
        if any(record.snapshot.fields.get(key) != value for key, value in expected.items()):
            await client.update_assignment_record(record.record_id, expected)
            updated_count += 1
    return updated_count, len(targets)


async def _verify_assignment_records(service, client, scopes) -> int:
    records = await client.list_record_snapshots()
    actual_by_number = {
        record.snapshot.fields.get("分配编号"): record.snapshot.fields
        for record in records
        if record.snapshot.fields.get("分配编号")
    }
    verified_count = 0
    mismatch_count = 0
    for tenant_id, shop_id in scopes:
        targets = await service._list_targets(tenant_id, shop_id, None)
        for outbox, application, _workflow, shop in targets:
            actual = actual_by_number.get(str(outbox.id))
            expected_creator_account = application.creator_username or ""
            if (
                actual is None
                or actual.get("达人ID") != expected_creator_account
                or actual.get("店铺名称") != shop.shop_name
            ):
                mismatch_count += 1
            else:
                verified_count += 1
    if mismatch_count:
        raise RuntimeError(
            f"Feishu assignment record verification failed: {mismatch_count} mismatch(es)."
        )
    return verified_count


if __name__ == "__main__":
    asyncio.run(main())
