from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import dataclass

from sqlalchemy import func, select

from erp_api.core.config import get_settings
from erp_api.infrastructure.database import Database
from erp_api.models.sample_application import SampleApplication
from erp_api.models.sample_application_workflow import SampleApplicationWorkflow
from erp_api.models.sample_notification_outbox import SampleNotificationOutbox
from erp_api.models.shop import Shop
from erp_api.services.feishu_assignment_record_client import (
    FeishuAssignmentRecordClient,
)
from erp_api.services.feishu_sample_batch_client import FeishuSampleBatchClient
from erp_api.services.sample_assignment_removal import (
    AssignmentRemovalTarget as Assignment,
)
from erp_api.services.sample_assignment_removal import suppress_sample_assignments
from erp_api.services.sample_feishu_client_router import SampleFeishuClientRouter


@dataclass(frozen=True)
class Target:
    creator: str
    assignment_record_id: str


def _normalize_creator(value: str) -> str:
    return value.strip().lstrip("@").casefold()


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--target",
        action="append",
        required=True,
        help="Exact creator and Feishu assignment record as creator=record_id.",
    )
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args()


def _parse_targets(values: list[str]) -> tuple[Target, ...]:
    targets = []
    for value in values:
        creator, separator, record_id = value.partition("=")
        creator = _normalize_creator(creator)
        record_id = record_id.strip()
        if not separator or not creator or not record_id:
            raise ValueError("Target must use creator=record_id.")
        targets.append(Target(creator, record_id))
    if len(targets) != len({target.creator for target in targets}):
        raise ValueError("Creator targets must be unique.")
    if len(targets) != len({target.assignment_record_id for target in targets}):
        raise ValueError("Assignment record targets must be unique.")
    return tuple(targets)


def _assignment_client(settings) -> FeishuAssignmentRecordClient:
    if not (
        settings.feishu_app_id
        and settings.feishu_app_secret
        and settings.feishu_sample_base_token
        and settings.feishu_bd_assignment_record_table_id
    ):
        raise RuntimeError("Feishu assignment record table is not configured.")
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
    default = (
        FeishuSampleBatchClient(**options, table_id=settings.feishu_sample_table_id)
        if settings.feishu_sample_table_id
        else None
    )
    clients = {
        shop_id: FeishuSampleBatchClient(**options, table_id=table_id)
        for shop_id, table_id in settings.feishu_sample_shop_table_ids.items()
    }
    return SampleFeishuClientRouter(default, clients)


async def _validate_feishu_records(client, targets: tuple[Target, ...]) -> None:
    by_creator: dict[str, list[str]] = {target.creator: [] for target in targets}
    for record in await client.list_record_snapshots():
        creator = record.snapshot.fields.get("达人ID")
        normalized = _normalize_creator(creator) if isinstance(creator, str) else ""
        if normalized in by_creator:
            by_creator[normalized].append(record.record_id)
    for target in targets:
        if by_creator[target.creator] != [target.assignment_record_id]:
            raise RuntimeError(
                f"Feishu target mismatch for {target.creator}: "
                f"{by_creator[target.creator]!r}."
            )


async def _load_assignments(
    database: Database, targets: tuple[Target, ...]
) -> tuple[Assignment, ...]:
    creators = tuple(target.creator for target in targets)
    creator_key = func.lower(func.ltrim(func.trim(SampleApplication.creator_username), "@"))
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
            (
                SampleNotificationOutbox.sample_application_id
                == SampleApplication.id
            )
            & (
                SampleNotificationOutbox.assignment_version
                == SampleApplicationWorkflow.assignment_version
            ),
        )
        .join(Shop, Shop.id == SampleApplication.shop_id)
        .where(
            creator_key.in_(creators),
            SampleApplication.is_current_projection.is_(True),
            SampleApplicationWorkflow.assigned_bd_name.is_not(None),
        )
        .order_by(SampleApplication.creator_username)
    )
    async with database.system_session_factory() as session:
        rows = tuple((await session.execute(statement)).all())
    target_map = {target.creator: target.assignment_record_id for target in targets}
    assignments = []
    for application, workflow, outbox, shop in rows:
        creator = _normalize_creator(application.creator_username or "")
        assignments.append(
            Assignment(
                creator=creator,
                application_id=application.id,
                platform_application_id=application.platform_application_id,
                shop_id=application.shop_id,
                shop_name=shop.shop_name,
                source_record_id=workflow.feishu_record_id or "",
                assigned_bd_name=workflow.assigned_bd_name,
                assignment_version=workflow.assignment_version,
                outbox_id=outbox.id,
                outbox_status=outbox.status,
                assignment_record_id=target_map[creator],
            )
        )
    counts = {creator: 0 for creator in creators}
    for assignment in assignments:
        counts[assignment.creator] += 1
    if any(count != 1 for count in counts.values()):
        raise RuntimeError(f"Expected one current DB assignment per creator: {counts!r}.")
    if any(not assignment.source_record_id for assignment in assignments):
        raise RuntimeError("A target assignment is missing its source Feishu record ID.")
    return tuple(assignments)


def _report(assignments: tuple[Assignment, ...], *, apply: bool) -> dict[str, object]:
    return {
        "apply": apply,
        "count": len(assignments),
        "assignments": [
            {
                "creator": item.creator,
                "shop": item.shop_name,
                "application": item.platform_application_id,
                "bd": item.assigned_bd_name,
                "outbox_status": item.outbox_status,
                "assignment_record_id": item.assignment_record_id,
            }
            for item in assignments
        ],
    }


async def main() -> None:
    arguments = _arguments()
    targets = _parse_targets(arguments.target)
    settings = get_settings()
    database = Database(settings.database_url)
    assignment_client = _assignment_client(settings)
    try:
        await _validate_feishu_records(assignment_client, targets)
        assignments = await _load_assignments(database, targets)
        print(json.dumps(_report(assignments, apply=arguments.apply), ensure_ascii=False))
        if not arguments.apply:
            return
        router = _source_router(settings)
        await suppress_sample_assignments(database, assignments)
        for assignment in assignments:
            await router.for_shop(assignment.shop_id).update_business_fields(
                assignment.source_record_id, {"分配BD": None}
            )
            await assignment_client.delete_assignment_record(
                assignment.assignment_record_id
            )
        print(json.dumps({"status": "removed", "count": len(assignments)}))
    finally:
        await database.dispose()


if __name__ == "__main__":
    asyncio.run(main())
