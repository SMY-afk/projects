from __future__ import annotations

import argparse
import asyncio
import json
from uuid import UUID

from sqlalchemy import select

from erp_api.core.config import get_settings
from erp_api.infrastructure.database import Database
from erp_api.models.sample_application import SampleApplication
from erp_api.models.sample_application_workflow import SampleApplicationWorkflow
from erp_api.models.sample_notification_outbox import SampleNotificationOutbox
from erp_api.services.sample_group_assignment_migration import (
    SampleGroupAssignmentMigrationService,
)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform-application-id", required=True)
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args()


def _parent_platform_id(application: SampleApplication) -> str:
    payload = application.raw_payload if isinstance(application.raw_payload, dict) else {}
    projection = payload.get("ziniao_group_projection")
    parent_id = (
        projection.get("parent_application_id")
        if isinstance(projection, dict)
        else None
    )
    if not isinstance(parent_id, str) or not parent_id:
        raise RuntimeError("The selected application has no grouped parent.")
    return parent_id


async def _report(database: Database, platform_application_id: str) -> dict[str, object]:
    async with database.system_session_factory() as session:
        child = await session.scalar(
            select(SampleApplication).where(
                SampleApplication.platform_application_id == platform_application_id
            )
        )
        if child is None:
            raise RuntimeError("The selected application does not exist.")
        parent_platform_id = _parent_platform_id(child)
        parent = await session.scalar(
            select(SampleApplication).where(
                SampleApplication.tenant_id == child.tenant_id,
                SampleApplication.shop_id == child.shop_id,
                SampleApplication.platform_application_id == parent_platform_id,
            )
        )
        if parent is None or not parent.is_current_projection:
            raise RuntimeError("The current grouped parent is unavailable.")
        application_ids = (child.id, parent.id)
        workflows = {
            item.sample_application_id: item
            for item in (
                await session.scalars(
                    select(SampleApplicationWorkflow).where(
                        SampleApplicationWorkflow.sample_application_id.in_(application_ids)
                    )
                )
            ).all()
        }
        outboxes = tuple(
            (
                await session.scalars(
                    select(SampleNotificationOutbox).where(
                        SampleNotificationOutbox.sample_application_id.in_(application_ids),
                        SampleNotificationOutbox.status != "cancelled",
                    )
                )
            ).all()
        )
    return {
        "child": {
            "id": str(child.id),
            "platform_application_id": child.platform_application_id,
            "current": child.is_current_projection,
            "bd": workflows[child.id].assigned_bd_name,
            "feishu_record_id": workflows[child.id].feishu_record_id,
        },
        "parent": {
            "id": str(parent.id),
            "platform_application_id": parent.platform_application_id,
            "current": parent.is_current_projection,
            "bd": workflows[parent.id].assigned_bd_name,
            "feishu_record_id": workflows[parent.id].feishu_record_id,
        },
        "active_outboxes": [
            {
                "id": str(item.id),
                "application_id": str(item.sample_application_id),
                "status": item.status,
                "assignment_version": item.assignment_version,
                "assignment_record_id": (item.payload or {}).get("assignment_record_id"),
            }
            for item in outboxes
        ],
    }


async def main() -> None:
    args = _arguments()
    settings = get_settings()
    database = Database(settings.database_url)
    try:
        before = await _report(database, args.platform_application_id)
        result: dict[str, object] = {"apply": args.apply, "before": before}
        if args.apply:
            child = before["child"]
            service = SampleGroupAssignmentMigrationService(database)
            migrated = await service.migrate(
                tenant_id=await _scope_id(
                    database, args.platform_application_id, SampleApplication.tenant_id
                ),
                shop_id=await _scope_id(
                    database, args.platform_application_id, SampleApplication.shop_id
                ),
                obsolete_platform_application_ids=frozenset(
                    {str(child["platform_application_id"])}
                ),
            )
            if migrated != {UUID(str(before["parent"]["id"]))}:
                raise RuntimeError("The exact grouped assignment was not migrated.")
            result["after"] = await _report(database, args.platform_application_id)
        print(json.dumps(result, ensure_ascii=True))
    finally:
        await database.dispose()


async def _scope_id(database: Database, platform_application_id: str, column) -> UUID:
    async with database.system_session_factory() as session:
        value = await session.scalar(
            select(column).where(
                SampleApplication.platform_application_id == platform_application_id
            )
        )
    if value is None:
        raise RuntimeError("The selected application scope is unavailable.")
    return value


if __name__ == "__main__":
    asyncio.run(main())
