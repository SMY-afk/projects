from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select

from erp_api.core.config import get_settings
from erp_api.infrastructure.database import Database
from erp_api.models.sample_application_workflow import SampleApplicationWorkflow
from erp_api.services.feishu_bd_roster_provider import FeishuBdRosterProvider
from erp_api.services.feishu_sample_batch_client import FeishuSampleBatchClient
from erp_api.services.sample_auto_assignment_feishu_service import (
    SampleAutoAssignmentFeishuService,
)
from erp_api.services.sample_auto_assignment_repository import (
    SampleAutoAssignmentRepository,
)
from erp_api.services.sample_auto_assignment_service import SampleAutoAssignmentService
from erp_api.services.sample_bd_assignment import validate_bd_roster


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant-id", type=UUID, required=True)
    parser.add_argument("--shop-id", type=UUID, required=True)
    parser.add_argument("--roster-table-id", required=True)
    parser.add_argument("--category", default="测试")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    if not (
        settings.feishu_app_id
        and settings.feishu_app_secret
        and settings.feishu_sample_base_token
    ):
        raise RuntimeError("Feishu sample connection is not configured.")
    database = Database(settings.database_url)
    try:
        sample_client = FeishuSampleBatchClient(
            app_id=settings.feishu_app_id,
            app_secret=settings.feishu_app_secret.get_secret_value(),
            base_token=settings.feishu_sample_base_token.get_secret_value(),
            table_id=settings.feishu_sample_table_id,
        )
        roster_client = FeishuSampleBatchClient(
            app_id=settings.feishu_app_id,
            app_secret=settings.feishu_app_secret.get_secret_value(),
            base_token=settings.feishu_sample_base_token.get_secret_value(),
            table_id=args.roster_table_id,
        )
        provider = FeishuBdRosterProvider(
            roster_client,
            allowed_bd_names={"李鸿程", "吴洵涛", "刘诚"},
            default_capacity=10,
        )
        repository = SampleAutoAssignmentRepository(
            database,
            category=args.category,
            batch_limit=1,
            activation_at=datetime.min.replace(tzinfo=UTC),
        )
        pending = await repository.list_pending(args.tenant_id, args.shop_id)
        roster = tuple(await provider.list_members(args.tenant_id, args.shop_id))
        validate_bd_roster(roster)
        print(
            json.dumps(
                {
                    "status": "ready",
                    "pending_count": len(pending),
                    "bd_names": sorted(member.name for member in roster),
                    "batch_limit": 1,
                    "apply": args.apply,
                },
                ensure_ascii=False,
            )
        )
        if not args.apply:
            return
        if len(pending) != 1:
            raise RuntimeError("Smoke test requires exactly one eligible sample.")
        service = SampleAutoAssignmentService(
            repository,
            provider,
            allowed_shop_ids=frozenset({args.shop_id}),
            rule_version="bd-v1-smoke",
        )
        result = await service.run_for_shop(
            tenant_id=args.tenant_id,
            shop_id=args.shop_id,
        )
        if result.assigned_count != 1:
            raise RuntimeError("Smoke assignment did not assign exactly one sample.")
        projected = await SampleAutoAssignmentFeishuService(
            database,
            sample_client,
            limit=1,
        ).sync(tenant_id=args.tenant_id, shop_id=args.shop_id)
        if projected.updated_count != 1:
            raise RuntimeError("Smoke assignment was not projected to Feishu.")
        record_id = await _record_id(database, pending[0].application_id)
        fields = await sample_client.get_record(record_id)
        assigned_name = result.items[0].decision.assigned_bd_name
        if fields.get("分配BD") != assigned_name:
            raise RuntimeError("Smoke assignment Feishu verification failed.")
        print(
            json.dumps(
                {
                    "status": "succeeded",
                    "assigned_bd_name": assigned_name,
                    "database_assigned": True,
                    "feishu_projected": True,
                    "notification_sent": False,
                },
                ensure_ascii=False,
            )
        )
    finally:
        await database.dispose()


async def _record_id(database: Database, application_id: UUID) -> str:
    async with database.system_session_factory() as session:
        record_id = await session.scalar(
            select(SampleApplicationWorkflow.feishu_record_id).where(
                SampleApplicationWorkflow.sample_application_id == application_id
            )
        )
    if not isinstance(record_id, str) or not record_id:
        raise RuntimeError("Smoke sample Feishu record identity is missing.")
    return record_id


if __name__ == "__main__":
    asyncio.run(main())
