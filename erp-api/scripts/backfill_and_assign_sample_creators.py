from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

from playwright.async_api import async_playwright
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from backend.app.services.hubstudio_attached_browser import (
    connect_attached_hubstudio_browser,
)
from backend.app.services.tiktok_sample_creator_details_collector import (
    SampleCreatorDetailsTarget,
    TikTokSampleCreatorDetailsCollector,
)
from erp_api.core.config import get_settings
from erp_api.infrastructure.database import Database
from erp_api.main import build_sample_application_services
from erp_api.models.sample_application import SampleApplication
from erp_api.models.sample_application_event import SampleApplicationEvent
from erp_api.models.sample_application_workflow import SampleApplicationWorkflow
from erp_api.models.sample_notification_outbox import SampleNotificationOutbox
from erp_api.services.feishu_assignment_record_client import (
    FeishuAssignmentRecordClient,
)
from erp_api.services.feishu_sample_batch_client import FeishuSampleBatchClient
from erp_api.services.sample_bd_assignment import classify_creator_level


def _target(value: str) -> tuple[str, str]:
    platform_id, separator, username = value.partition("=")
    if not separator or not platform_id.strip() or not username.strip():
        raise argparse.ArgumentTypeError("Target must be APPLICATION_ID=USERNAME.")
    return platform_id.strip(), username.strip().lstrip("@").casefold()


def _gmv_fallback(value: str) -> tuple[str, int]:
    platform_id, separator, raw_minor = value.partition("=")
    try:
        minor = int(raw_minor)
    except ValueError as error:
        raise argparse.ArgumentTypeError("GMV fallback minor value is invalid.") from error
    if not separator or not platform_id.strip() or minor < 0:
        raise argparse.ArgumentTypeError("GMV fallback must be APPLICATION_ID=MINOR.")
    return platform_id.strip(), minor


async def _applications(database, tenant_id, shop_id, targets):
    platform_ids = [platform_id for platform_id, _username in targets]
    statement = (
        select(SampleApplication, SampleApplicationWorkflow)
        .outerjoin(
            SampleApplicationWorkflow,
            SampleApplicationWorkflow.sample_application_id == SampleApplication.id,
        )
        .where(
            SampleApplication.tenant_id == tenant_id,
            SampleApplication.shop_id == shop_id,
            SampleApplication.platform_application_id.in_(platform_ids),
        )
    )
    async with database.system_session_factory() as session:
        rows = (await session.execute(statement)).all()
    applications = []
    for application, workflow in rows:
        application.feishu_record_id = (
            workflow.feishu_record_id if workflow is not None else None
        )
        application.assigned_bd_name = (
            workflow.assigned_bd_name if workflow is not None else None
        )
        applications.append(application)
    by_platform_id = {item.platform_application_id: item for item in applications}
    if set(by_platform_id) != set(platform_ids) or len(applications) != len(targets):
        raise RuntimeError("Exact sample application scope is missing or ambiguous.")
    for platform_id, username in targets:
        application = by_platform_id[platform_id]
        actual = (application.creator_username or "").lstrip("@").casefold()
        if actual != username:
            raise RuntimeError("Sample application username does not match target.")
        if application.platform_status != "PENDING":
            raise RuntimeError("Sample application is not pending.")
        if not application.is_current_projection:
            raise RuntimeError("Sample application is not the current projection.")
        if not application.feishu_record_id:
            raise RuntimeError("Sample application has no persisted Feishu record_id.")
    return tuple(by_platform_id[platform_id] for platform_id in platform_ids)


async def _database_readback(database, tenant_id, shop_id, application_ids):
    application_statement = (
        select(SampleApplication, SampleApplicationWorkflow)
        .join(
            SampleApplicationWorkflow,
            SampleApplicationWorkflow.sample_application_id == SampleApplication.id,
        )
        .where(
            SampleApplication.tenant_id == tenant_id,
            SampleApplication.shop_id == shop_id,
            SampleApplication.id.in_(application_ids),
        )
    )
    event_statement = (
        select(SampleApplicationEvent)
        .where(
            SampleApplicationEvent.tenant_id == tenant_id,
            SampleApplicationEvent.shop_id == shop_id,
            SampleApplicationEvent.sample_application_id.in_(application_ids),
        )
        .order_by(SampleApplicationEvent.occurred_at.desc())
    )
    outbox_statement = select(SampleNotificationOutbox).where(
        SampleNotificationOutbox.tenant_id == tenant_id,
        SampleNotificationOutbox.shop_id == shop_id,
        SampleNotificationOutbox.sample_application_id.in_(application_ids),
    )
    async with database.system_session_factory() as session:
        application_rows = (await session.execute(application_statement)).all()
        events = (await session.scalars(event_statement)).all()
        outboxes = (await session.scalars(outbox_statement)).all()
    return {
        "applications": [
            {
                "id": str(application.id),
                "platform_application_id": application.platform_application_id,
                "creator_username": application.creator_username,
                "gmv_minor": application.creator_gmv_minor,
                "gmv_currency": application.creator_gmv_currency,
                "creator_level": application.creator_level,
                "assigned_bd_name": workflow.assigned_bd_name,
                "feishu_record_id": workflow.feishu_record_id,
                "profile_observed_at": application.creator_profile_observed_at,
            }
            for application, workflow in application_rows
        ],
        "events": [
            {
                "application_id": str(item.sample_application_id),
                "event_type": item.event_type,
                "event_source": item.event_source,
                "occurred_at": item.occurred_at,
            }
            for item in events
        ],
        "outboxes": [
            {
                "application_id": str(item.sample_application_id),
                "status": item.status,
                "sent_at": item.sent_at,
                "last_error_code": item.last_error_code,
            }
            for item in outboxes
        ],
    }


async def _apply_gmv_fallbacks(database, tenant_id, shop_id, fallbacks) -> int:
    changed = 0
    for platform_id, gmv_minor in fallbacks:
        async with database.system_session_factory() as session:
            application = await session.scalar(
                select(SampleApplication)
                .where(
                    SampleApplication.tenant_id == tenant_id,
                    SampleApplication.shop_id == shop_id,
                    SampleApplication.platform_application_id == platform_id,
                    SampleApplication.platform_status == "PENDING",
                    SampleApplication.is_current_projection.is_(True),
                )
                .with_for_update()
            )
            if application is None:
                raise RuntimeError("GMV fallback target is missing or not current.")
            if application.creator_gmv_minor is not None:
                continue
            before = {
                "creator_gmv_minor": None,
                "creator_gmv_currency": application.creator_gmv_currency,
                "creator_level": application.creator_level,
            }
            application.creator_gmv_minor = gmv_minor
            application.creator_gmv_currency = "USD"
            application.creator_level = classify_creator_level(gmv_minor)
            now = datetime.now(UTC)
            statement = insert(SampleApplicationEvent).values(
                tenant_id=tenant_id,
                shop_id=shop_id,
                sample_application_id=application.id,
                event_type="creator_gmv_backfilled",
                event_source="operator_screenshot",
                external_event_id=f"gmv-backfill:{platform_id}:{gmv_minor}",
                actor_name="Codex operator repair",
                before_data=before,
                after_data={
                    "creator_gmv_minor": gmv_minor,
                    "creator_gmv_currency": "USD",
                    "creator_level": application.creator_level,
                },
                occurred_at=now,
            )
            await session.execute(
                statement.on_conflict_do_nothing(
                    constraint="uq_sample_application_events_tenant_shop_source_external"
                )
            )
            await session.commit()
            changed += 1
    return changed


async def _feishu_readback(settings, shop_id, applications):
    table_id = settings.feishu_sample_shop_table_ids.get(shop_id)
    if not table_id:
        table_id = settings.feishu_sample_table_id
    client_options = {
        "app_id": settings.feishu_app_id,
        "app_secret": settings.feishu_app_secret.get_secret_value(),
        "base_token": settings.feishu_sample_base_token.get_secret_value(),
    }
    sample_client = FeishuSampleBatchClient(**client_options, table_id=table_id)
    sample_rows = []
    for application in applications:
        snapshot = await sample_client.get_record_snapshot(application.feishu_record_id)
        fields = snapshot.fields
        sample_rows.append(
            {
                "record_id": application.feishu_record_id,
                "platform_application_id": application.platform_application_id,
                "creator": fields.get("达人账号"),
                "gmv": fields.get("30日GMV"),
                "level": fields.get("达人等级"),
                "bd": fields.get("分配BD"),
            }
        )
    assignment_client = FeishuAssignmentRecordClient(
        **client_options,
        table_id=settings.feishu_bd_assignment_record_table_id,
    )
    usernames = {
        (application.creator_username or "").lstrip("@").casefold()
        for application in applications
    }
    assignments = []
    for record in await assignment_client.list_record_snapshots():
        fields = record.snapshot.fields
        creator = str(fields.get("达人ID") or "").lstrip("@").casefold()
        if creator in usernames:
            assignments.append(
                {
                    "record_id": record.record_id,
                    "creator": fields.get("达人ID"),
                    "shop": fields.get("店铺名称"),
                    "bd": fields.get("分配BD"),
                    "notification_status": fields.get("通知状态"),
                    "notification_time": fields.get("通知时间"),
                }
            )
    return {"sample_rows": sample_rows, "assignment_rows": assignments}


def _json(value):
    if is_dataclass(value):
        return asdict(value)
    return str(value)


async def run(arguments) -> None:
    settings = get_settings()
    database = Database(settings.database_url)
    try:
        applications = await _applications(
            database, arguments.tenant_id, arguments.shop_id, arguments.target
        )
        if arguments.readback_only:
            database_readback = await _database_readback(
                database,
                arguments.tenant_id,
                arguments.shop_id,
                frozenset(item.id for item in applications),
            )
            feishu_readback = await _feishu_readback(
                settings, arguments.shop_id, applications
            )
            print(
                json.dumps(
                    {
                        "database_readback": database_readback,
                        "feishu_readback": feishu_readback,
                    },
                    ensure_ascii=False,
                    default=_json,
                )
            )
            return
        captured = 0
        if not arguments.skip_capture:
            collector = TikTokSampleCreatorDetailsCollector(
                arguments.tenant_id,
                arguments.shop_id,
                arguments.platform_shop_id,
                database,
            )
            targets = [
                SampleCreatorDetailsTarget(username, frozenset({application.id}))
                for application, (_platform_id, username) in zip(
                    applications, arguments.target, strict=True
                )
            ]
            async with async_playwright() as playwright:
                browser = await connect_attached_hubstudio_browser(
                    playwright, arguments.cdp_url
                )
                captured = await collector.capture(browser.contexts, targets)
            if captured != len(targets):
                raise RuntimeError("Targeted creator profile capture is incomplete.")

        fallback_count = await _apply_gmv_fallbacks(
            database,
            arguments.tenant_id,
            arguments.shop_id,
            arguments.gmv_fallback,
        )

        applications = await _applications(
            database, arguments.tenant_id, arguments.shop_id, arguments.target
        )
        if any(
            item.creator_gmv_minor is None or item.creator_level is None
            for item in applications
        ):
            raise RuntimeError("Captured profile did not backfill assignment GMV.")

        services = build_sample_application_services(settings, database)
        pipeline = services["sample_shop_pipeline_service"]
        if pipeline is None:
            raise RuntimeError("Sample shop pipeline is not configured.")
        result = await pipeline.complete_after_source(
            tenant_id=arguments.tenant_id,
            shop_id=arguments.shop_id,
            source_type="hubstudio_cdp",
            source_results=(
                SimpleNamespace(
                    application_ids=frozenset(item.id for item in applications),
                    obsolete_platform_application_ids=frozenset(),
                ),
            ),
        )
        database_readback = await _database_readback(
            database,
            arguments.tenant_id,
            arguments.shop_id,
            frozenset(item.id for item in applications),
        )
        applications = await _applications(
            database, arguments.tenant_id, arguments.shop_id, arguments.target
        )
        feishu_readback = await _feishu_readback(
            settings, arguments.shop_id, applications
        )
        print(
            json.dumps(
                {
                    "captured": captured,
                    "gmv_fallbacks": fallback_count,
                    "pipeline": result,
                    "database_readback": database_readback,
                    "feishu_readback": feishu_readback,
                },
                ensure_ascii=False,
                default=_json,
            )
        )
    finally:
        await database.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant-id", type=UUID, required=True)
    parser.add_argument("--shop-id", type=UUID, required=True)
    parser.add_argument("--platform-shop-id", required=True)
    parser.add_argument("--cdp-url", required=True)
    parser.add_argument("--target", type=_target, action="append", required=True)
    parser.add_argument("--gmv-fallback", type=_gmv_fallback, action="append", default=[])
    parser.add_argument("--skip-capture", action="store_true")
    parser.add_argument("--readback-only", action="store_true")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
