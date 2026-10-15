from __future__ import annotations

import argparse
import asyncio
import json
import re
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select

from erp_api.core.config import get_settings
from erp_api.infrastructure.database import Database
from erp_api.models.sample_notification_outbox import SampleNotificationOutbox
from erp_api.services.feishu_assignment_record_client import (
    FeishuAssignmentRecordClient,
)
from erp_api.services.feishu_bd_roster_provider import FeishuBdRosterProvider
from erp_api.services.feishu_notification_client import FeishuNotificationClient
from erp_api.services.feishu_sample_batch_client import FeishuSampleBatchClient
from erp_api.services.sample_assignment_record_service import (
    SampleAssignmentRecordService,
)
from erp_api.services.sample_auto_assignment_feishu_service import (
    SampleAutoAssignmentFeishuService,
)
from erp_api.services.sample_auto_assignment_repository import (
    SampleAutoAssignmentRepository,
)
from erp_api.services.sample_auto_assignment_service import SampleAutoAssignmentService
from erp_api.services.sample_notification_profile_enrichment import (
    SampleNotificationProfileEnrichmentService,
)
from erp_api.services.sample_notification_repository import (
    SampleNotificationRepository,
)
from erp_api.services.sample_notification_service import SampleNotificationService

BD_NAMES = frozenset({"李鸿程", "吴洵涛", "刘诚"})
RULE_VERSION = "bd-v1-smoke"


async def main() -> None:
    args = _arguments()
    settings = get_settings()
    _validate_settings(settings)
    database = Database(settings.database_url)
    try:
        sample_client = _sample_client(settings, settings.feishu_sample_table_id)
        roster_client = _sample_client(settings, args.roster_table_id)
        record_client = FeishuAssignmentRecordClient(
            app_id=settings.feishu_app_id,
            app_secret=settings.feishu_app_secret.get_secret_value(),
            base_token=settings.feishu_sample_base_token.get_secret_value(),
            table_id=args.assignment_table_id,
        )
        provider = FeishuBdRosterProvider(
            roster_client,
            allowed_bd_names=BD_NAMES,
            default_capacity=10,
        )
        await provider.list_members(args.tenant_id, args.shop_id)
        existing = await _smoke_outboxes(database, args.tenant_id, args.shop_id)
        existing_names = _unique_names(existing)
        missing = BD_NAMES - existing_names
        print(
            json.dumps(
                {
                    "status": "ready",
                    "existing_bd_names": sorted(existing_names),
                    "missing_bd_names": sorted(missing),
                    "notification_statuses": {
                        _bd_name(item): item.status for item in existing
                    },
                    "notification_evidence": {
                        _bd_name(item): {
                            "attempt_count": item.attempt_count,
                            "message_recorded": bool(
                                isinstance(item.payload, dict)
                                and item.payload.get("message_id")
                            ),
                            "last_error_code": item.last_error_code,
                        }
                        for item in existing
                    },
                    "target_count": 3,
                    "apply": args.apply,
                },
                ensure_ascii=False,
            )
        )
        if not args.apply:
            return
        repository = SampleAutoAssignmentRepository(
            database,
            category="测试",
            batch_limit=1,
            activation_at=datetime.min.replace(tzinfo=UTC),
        )
        assignment_service = SampleAutoAssignmentService(
            repository,
            provider,
            allowed_shop_ids=frozenset({args.shop_id}),
            rule_version=RULE_VERSION,
        )
        sample_projection = SampleAutoAssignmentFeishuService(
            database, sample_client, limit=3
        )
        while missing:
            result = await assignment_service.run_for_shop(
                tenant_id=args.tenant_id,
                shop_id=args.shop_id,
            )
            if result.assigned_count != 1:
                raise RuntimeError("Live smoke did not create exactly one assignment.")
            assigned_name = result.items[0].decision.assigned_bd_name
            if assigned_name not in missing:
                raise RuntimeError("Live smoke selected a BD that was already covered.")
            await sample_projection.sync(
                tenant_id=args.tenant_id,
                shop_id=args.shop_id,
            )
            missing = missing - {assigned_name}
        targets = await _smoke_outboxes(database, args.tenant_id, args.shop_id)
        if _unique_names(targets) != BD_NAMES or len(targets) != 3:
            raise RuntimeError("Live smoke assignment coverage is incomplete.")
        notification_repository = SampleNotificationRepository(database)
        if args.retry_failed_bd:
            target = next(
                (item for item in targets if _bd_name(item) == args.retry_failed_bd),
                None,
            )
            if target is None:
                raise RuntimeError("Retry target was not found.")
            requeued = await notification_repository.requeue_unavailable_recipient(
                args.tenant_id,
                target.id,
                now=datetime.now(UTC),
            )
            if not requeued and target.status != "sent":
                raise RuntimeError("Retry target is not safely requeueable.")
            targets = await _smoke_outboxes(database, args.tenant_id, args.shop_id)
        target_ids = frozenset(item.id for item in targets)
        enrichment = await SampleNotificationProfileEnrichmentService(
            database,
            limit=3,
        ).enrich(
            tenant_id=args.tenant_id,
            shop_id=args.shop_id,
            outbox_ids=target_ids,
        )
        record_service = SampleAssignmentRecordService(database, record_client, limit=3)
        await record_service.sync(
            tenant_id=args.tenant_id,
            shop_id=args.shop_id,
            outbox_ids=target_ids,
        )
        notification_service = SampleNotificationService(
            notification_repository,
            FeishuNotificationClient(sample_client),
            sample_client,
            record_url_template=_record_url_template(args.tenant_domain, settings),
            test_recipient_open_id=None,
            live_recipients_enabled=True,
            max_attempts=1,
            retry_base_seconds=30,
            processing_timeout=timedelta(minutes=10),
        )
        delivery = {}
        for target in targets:
            result = await notification_service.deliver(args.tenant_id, target.id)
            if result.status not in {"sent", "skipped"}:
                raise RuntimeError(
                    f"Live notification stopped with status: {result.status}."
                )
            delivery[_bd_name(target)] = result.status
            await record_service.sync(
                tenant_id=args.tenant_id,
                shop_id=args.shop_id,
                outbox_ids=frozenset({target.id}),
            )
        verified = await _smoke_outboxes(database, args.tenant_id, args.shop_id)
        if len(verified) != 3 or any(item.status != "sent" for item in verified):
            raise RuntimeError("Live notification database verification failed.")
        print(
            json.dumps(
                {
                    "status": "succeeded",
                    "assigned_bd_names": sorted(_unique_names(verified)),
                    "assignment_records": 3,
                    "profile_enrichment": {
                        "enriched": enrichment.enriched_count,
                        "unavailable": enrichment.unavailable_count,
                        "skipped": enrichment.skipped_count,
                    },
                    "notifications": delivery,
                },
                ensure_ascii=False,
            )
        )
    finally:
        await database.dispose()


def _arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant-id", type=UUID, required=True)
    parser.add_argument("--shop-id", type=UUID, required=True)
    parser.add_argument("--roster-table-id", required=True)
    parser.add_argument("--assignment-table-id", required=True)
    parser.add_argument("--tenant-domain", required=True)
    parser.add_argument("--retry-failed-bd", choices=sorted(BD_NAMES))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9-]+\.feishu\.cn", args.tenant_domain):
        raise ValueError("Feishu tenant domain is invalid.")
    if not all(
        value.startswith("tbl")
        for value in (args.roster_table_id, args.assignment_table_id)
    ):
        raise ValueError("Feishu smoke table ID is invalid.")
    return args


def _validate_settings(settings) -> None:
    if not (
        settings.feishu_app_id
        and settings.feishu_app_secret
        and settings.feishu_sample_base_token
        and settings.feishu_sample_table_id
    ):
        raise RuntimeError("Feishu sample connection is not configured.")


def _sample_client(settings, table_id):
    return FeishuSampleBatchClient(
        app_id=settings.feishu_app_id,
        app_secret=settings.feishu_app_secret.get_secret_value(),
        base_token=settings.feishu_sample_base_token.get_secret_value(),
        table_id=table_id,
    )


async def _smoke_outboxes(database, tenant_id, shop_id):
    statement = (
        select(SampleNotificationOutbox)
        .where(
            SampleNotificationOutbox.tenant_id == tenant_id,
            SampleNotificationOutbox.shop_id == shop_id,
            SampleNotificationOutbox.payload["source_event_id"].astext.like(
                f"bd-auto:{RULE_VERSION}:%"
            ),
        )
        .order_by(SampleNotificationOutbox.created_at)
    )
    async with database.system_session_factory() as session:
        return tuple((await session.execute(statement)).scalars())


def _unique_names(outboxes) -> frozenset[str]:
    names = [_bd_name(item) for item in outboxes]
    if len(names) != len(set(names)):
        raise RuntimeError("Live smoke contains duplicate BD assignments.")
    return frozenset(names)


def _bd_name(outbox) -> str:
    payload = outbox.payload if isinstance(outbox.payload, dict) else {}
    name = payload.get("assigned_bd_name")
    if not isinstance(name, str) or name not in BD_NAMES:
        raise RuntimeError("Live smoke outbox contains an unexpected BD.")
    return name


def _record_url_template(domain: str, settings) -> str:
    base_token = settings.feishu_sample_base_token.get_secret_value()
    return (
        f"https://{domain}/base/{base_token}"
        f"?table={settings.feishu_sample_table_id}&record={{record_id}}"
    )


if __name__ == "__main__":
    asyncio.run(main())
