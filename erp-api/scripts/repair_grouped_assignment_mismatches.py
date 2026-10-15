from __future__ import annotations

import argparse
import asyncio
import json
from collections import defaultdict
from datetime import UTC, datetime
from uuid import UUID, uuid4

from grouped_assignment_repair_feishu import (
    application_id_for_outbox,
    canonical_targets,
    repair_feishu,
)
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from erp_api.core.config import get_settings
from erp_api.infrastructure.database import Database
from erp_api.models.sample_application import SampleApplication
from erp_api.models.sample_application_event import SampleApplicationEvent
from erp_api.models.sample_application_workflow import SampleApplicationWorkflow
from erp_api.models.sample_notification_outbox import SampleNotificationOutbox
from erp_api.services.sample_group_assignment_migration import (
    SampleGroupAssignmentMigrationService,
)

GROUPED_CHILD_IDS = frozenset(
    {
        "9861101767501540279",
        "9698040229646012362",
        "9849490246550924098",
        "9437291680371036073",
        "9476208504985805082",
        "9164983107806069695",
        "9103781442503327790",
        "9434265977693663116",
        "9945799588474633228",
        "9345695119973116205",
        "9664988392958983232",
        "9485312664909639806",
        "9395988874437249593",
        "9765583142028134211",
        "9465194006925122940",
        "9456215250704800304",
        "9910003219103695348",
        "9365448331811163309",
    }
)
HOUSEHOLD_OUTBOX_ID = UUID("d7db0675-4ca8-5da8-9b4f-a3e2e97cffc8")
SAVE_OUTBOX_ID = UUID("fda532e3-92ae-5631-9f49-411db81b767b")
HEY_ASSIGNMENT_NUMBER = "e8aa1a35-4c8a-5483-a00b-ed9e827cca4c"
HEY_APPLICATION_ID = "9331705347320441332"

def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args()


async def _group_scope(database: Database):
    statement = select(SampleApplication).where(
        SampleApplication.platform_application_id.in_(GROUPED_CHILD_IDS)
    )
    async with database.system_session_factory() as session:
        children = tuple((await session.scalars(statement)).all())
    if {item.platform_application_id for item in children} != GROUPED_CHILD_IDS:
        raise RuntimeError("The exact grouped-child scope is incomplete.")
    if any(item.is_current_projection for item in children):
        raise RuntimeError("A grouped-child target unexpectedly became current.")
    tenant_ids = {item.tenant_id for item in children}
    if len(tenant_ids) != 1:
        raise RuntimeError("The repair targets span multiple tenants.")
    by_shop = defaultdict(set)
    for child in children:
        by_shop[child.shop_id].add(child.platform_application_id)
    return next(iter(tenant_ids)), by_shop


async def _apply_special_repairs(database: Database, tenant_id: UUID) -> None:
    now = datetime.now(UTC)
    async with database.system_session_factory() as session:
        outboxes = tuple(
            (
                await session.scalars(
                    select(SampleNotificationOutbox)
                    .where(
                        SampleNotificationOutbox.id.in_(
                            (HOUSEHOLD_OUTBOX_ID, SAVE_OUTBOX_ID)
                        )
                    )
                    .with_for_update()
                )
            ).all()
        )
        by_id = {item.id: item for item in outboxes}
        if set(by_id) != {HOUSEHOLD_OUTBOX_ID, SAVE_OUTBOX_ID}:
            raise RuntimeError("A special repair outbox is unavailable.")
        household = by_id[HOUSEHOLD_OUTBOX_ID]
        household_workflow = await session.scalar(
            select(SampleApplicationWorkflow)
            .where(
                SampleApplicationWorkflow.sample_application_id
                == household.sample_application_id
            )
            .with_for_update()
        )
        if household_workflow is None or household.status != "sent":
            raise RuntimeError("The household assignment is not repairable.")
        household.assignment_version = household_workflow.assignment_version

        save = by_id[SAVE_OUTBOX_ID]
        save.status = "cancelled"
        save.next_attempt_at = None
        save.last_error_code = "current_application_unassigned"
        save.last_error_summary = "The current application has no active assignment."

        hey_application = await session.scalar(
            select(SampleApplication).where(
                SampleApplication.platform_application_id == HEY_APPLICATION_ID
            )
        )
        if hey_application is None or hey_application.is_current_projection:
            raise RuntimeError("The heyitszelda grouped child is not repairable.")
        hey_outboxes = tuple(
            (
                await session.scalars(
                    select(SampleNotificationOutbox)
                    .where(
                        SampleNotificationOutbox.sample_application_id
                        == hey_application.id,
                        SampleNotificationOutbox.status != "cancelled",
                    )
                    .with_for_update()
                )
            ).all()
        )
        for outbox in hey_outboxes:
            outbox.status = "cancelled"
            outbox.next_attempt_at = None
            outbox.last_error_code = "obsolete_group_projection"
            outbox.last_error_summary = "The application was superseded by its group."
        for application_id, shop_id, external_id, before, after in (
            (
                household.sample_application_id,
                household.shop_id,
                f"assignment-version-aligned:{household.id}",
                {"assignment_version": 1},
                {"assignment_version": household_workflow.assignment_version},
            ),
            (
                save.sample_application_id,
                save.shop_id,
                f"stale-assignment-cancelled:{save.id}",
                {"status": "sent"},
                {"status": "cancelled"},
            ),
            (
                hey_application.id,
                hey_application.shop_id,
                f"obsolete-assignment-cancelled:{HEY_ASSIGNMENT_NUMBER}",
                {"active_outbox_count": len(hey_outboxes)},
                {"active_outbox_count": 0},
            ),
        ):
            await session.execute(
                insert(SampleApplicationEvent)
                .values(
                    id=uuid4(),
                    tenant_id=tenant_id,
                    shop_id=shop_id,
                    sample_application_id=application_id,
                    event_type="assignment_projection_repaired",
                    event_source="exact_application_repair",
                    external_event_id=external_id,
                    actor_name="Codex exact repair",
                    before_data=before,
                    after_data=after,
                    occurred_at=now,
                )
                .on_conflict_do_nothing(
                    constraint=(
                        "uq_sample_application_events_tenant_shop_source_external"
                    )
                )
            )
        await session.commit()


async def main() -> None:
    args = _arguments()
    settings = get_settings()
    database = Database(settings.database_url)
    try:
        tenant_id, by_shop = await _group_scope(database)
        preview = {
            "apply": args.apply,
            "grouped_children": sum(len(items) for items in by_shop.values()),
            "shops": {str(key): sorted(value) for key, value in by_shop.items()},
            "special_rows": 3,
            "exact_repair_count": len(GROUPED_CHILD_IDS) + 3,
        }
        print(json.dumps(preview, ensure_ascii=True))
        if not args.apply:
            return
        migration = SampleGroupAssignmentMigrationService(database)
        parent_ids: set[UUID] = set()
        for shop_id, child_ids in by_shop.items():
            parent_ids.update(
                await migration.migrate(
                    tenant_id=tenant_id,
                    shop_id=shop_id,
                    obsolete_platform_application_ids=frozenset(child_ids),
                )
            )
        if len(parent_ids) != len(GROUPED_CHILD_IDS):
            raise RuntimeError("Not every grouped assignment was migrated.")
        await _apply_special_repairs(database, tenant_id)
        household_application_id = await application_id_for_outbox(
            database, HOUSEHOLD_OUTBOX_ID
        )
        targets = await canonical_targets(
            database, parent_ids | {household_application_id}
        )
        result = await repair_feishu(
            settings,
            targets,
            save_outbox_id=SAVE_OUTBOX_ID,
            hey_assignment_number=HEY_ASSIGNMENT_NUMBER,
        )
        print(json.dumps({"status": "repaired", **result}, ensure_ascii=True))
    finally:
        await database.dispose()


if __name__ == "__main__":
    asyncio.run(main())
