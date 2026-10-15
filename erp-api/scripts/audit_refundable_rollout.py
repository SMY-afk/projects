"""Read-only evidence for free continuity and paid end-to-end processing."""

import asyncio
import json

from sqlalchemy import func, select, text

from erp_api.core.config import get_settings
from erp_api.infrastructure.database import Database
from erp_api.infrastructure.health import probe_dependencies
from erp_api.models.sample_application import SampleApplication
from erp_api.models.sample_application_event import SampleApplicationEvent
from erp_api.models.sample_application_workflow import SampleApplicationWorkflow
from erp_api.models.sample_ingest_batch import SampleIngestBatch
from erp_api.models.sample_notification_outbox import SampleNotificationOutbox
from erp_api.models.shop import Shop
from erp_api.services.feishu_assignment_record_client import (
    FeishuAssignmentRecordClient,
)
from erp_api.services.feishu_assignment_summary_client import (
    FeishuAssignmentSummaryClient,
)
from erp_api.services.sample_assignment_summary_repository import (
    SampleAssignmentSummaryRepository,
)
from erp_api.services.sample_assignment_summary_service import (
    SampleAssignmentSummaryService,
)


class SummaryPreview:
    """Collect the diff without issuing any Feishu mutations."""

    def __init__(self, rows):
        self.rows, self.updates, self.creates = rows, [], []

    async def list_record_snapshots(self):
        return self.rows

    async def batch_update_summary_records(self, rows):
        self.updates.extend(rows)

    async def batch_create_summary_records(self, rows):
        self.creates.extend(rows)


async def run():
    settings = get_settings()
    database = Database(settings.database_url)
    try:
        dependencies = await probe_dependencies(database, settings.redis_url, sample_sync_enabled=True)
        report = {"dependencies": dependencies, "paid_enabled": settings.feishu_refundable_sample_enabled}
        async with database.system_session_factory() as session:
            rows = (await session.execute(select(
                Shop.shop_name, SampleApplication.platform_status, SampleApplication.creator_level,
                func.count(SampleApplication.id),
            ).join(Shop, Shop.id == SampleApplication.shop_id)
              .where(SampleApplication.sample_type == "refundable")
              .group_by(Shop.shop_name, SampleApplication.platform_status, SampleApplication.creator_level))).all()
            report["paid_sources"] = [{"shop": shop, "status": status, "level": level, "count": count} for shop, status, level, count in rows]
            rows = (await session.execute(select(
                SampleApplicationEvent.event_type, SampleApplicationEvent.after_data["blocked_reason"].astext,
                SampleApplicationEvent.after_data["reason"].astext, func.count(SampleApplicationEvent.id),
            ).join(SampleApplication, SampleApplication.id == SampleApplicationEvent.sample_application_id)
              .where(SampleApplication.sample_type == "refundable")
              .group_by(text("1"), text("2"), text("3")))).all()
            report["paid_events"] = [{"event": event, "blocked": blocked, "reason": reason, "count": count} for event, blocked, reason, count in rows]
            rows = (await session.execute(select(
                SampleNotificationOutbox.status, func.count(SampleNotificationOutbox.id),
            ).join(SampleApplication, SampleApplication.id == SampleNotificationOutbox.sample_application_id)
              .where(SampleApplication.sample_type == "refundable")
              .group_by(SampleNotificationOutbox.status))).all()
            report["paid_notifications"] = [{"status": status, "count": count} for status, count in rows]
            report["paid_sample_records"] = await session.scalar(select(func.count(SampleApplicationWorkflow.id))
                .join(SampleApplication, SampleApplication.id == SampleApplicationWorkflow.sample_application_id)
                .where(SampleApplication.sample_type == "refundable", SampleApplicationWorkflow.feishu_record_id.is_not(None)))
            rows = (await session.execute(select(Shop.shop_name, SampleIngestBatch.sample_type,
                func.max(SampleIngestBatch.finished_at)).join(Shop, Shop.id == SampleIngestBatch.shop_id)
                .where(SampleIngestBatch.status == "complete")
                .group_by(Shop.shop_name, SampleIngestBatch.sample_type))).all()
            report["source_watermarks"] = [{"shop": shop, "kind": kind, "at": at.isoformat()} for shop, kind, at in rows]
        if all(dependencies.get(key) == "ok" for key in ("database", "redis", "sample_schema", "sample_worker")):
            options = {"app_id": settings.feishu_app_id,
                       "app_secret": settings.feishu_app_secret.get_secret_value(),
                       "base_token": settings.feishu_sample_base_token.get_secret_value()}
            client = FeishuAssignmentRecordClient(**options, table_id=settings.feishu_refundable_assignment_record_table_id)
            records = await client.list_record_snapshots()
            report["paid_assignment_records"] = len(records)
            summary = FeishuAssignmentSummaryClient(**options, table_id=settings.feishu_refundable_assignment_summary_table_id)
            metadata = await summary.list_field_metadata()
            report["paid_summary_schema_verified"] = all(
                name in metadata and metadata[name].field_type == kind
                for name, kind in [("店铺｜BD", 1), ("店铺分配总计", 2),
                                   *((f"L{i}", 2) for i in range(8))]
            )
            original = FeishuAssignmentSummaryClient(
                **options, table_id=settings.feishu_assignment_summary_table_id,
            )
            original_fields = await original.list_field_metadata()
            report["original_summary_paid_columns_remaining"] = sum(
                name in original_fields for name in [*(f"买返 L{i}" for i in range(8)), "买返样品总计"]
            )
            summary_rows = await summary.list_record_snapshots()
            report["paid_summary_rows"] = len(summary_rows)
            preview = SummaryPreview(summary_rows)
            service = SampleAssignmentSummaryService(
                SampleAssignmentSummaryRepository(database), client, preview,
                allowed_shop_ids=settings.assignment_summary_shop_id_set,
                bd_names=settings.assignment_summary_bd_names,
                bd_aliases=settings.feishu_assignment_summary_bd_aliases,
                sample_type="refundable",
            )
            result = await service.sync()
            keys = [row.snapshot.fields.get("店铺｜BD") for row in summary_rows]
            shop_names = await SampleAssignmentSummaryRepository(database).list_shop_names(
                settings.assignment_summary_shop_id_set,
            )
            expected = {f"{shop}｜{bd.strip()}" for shop in shop_names
                        for bd in settings.assignment_summary_bd_names if bd.strip()}
            report["paid_summary_verification"] = {
                "shop_count": len(shop_names), "bd_count": len(set(settings.assignment_summary_bd_names)),
                "expected_shop_bd_rows": len(expected), "missing_rows": len(expected - set(keys)),
                "duplicate_rows": len(keys) - len(set(keys)),
                "source_count": result.source_count,
                "preview_create": len(preview.creates), "preview_update": len(preview.updates),
                "row_total_mismatches": sum(
                    int(float(row.snapshot.fields.get("店铺分配总计") or 0))
                    != sum(int(float(row.snapshot.fields.get(f"L{i}") or 0)) for i in range(8))
                    for row in summary_rows if row.snapshot.fields.get("店铺｜BD") in expected
                ),
            }
            report["paid_summary_totals"] = [
                {key: row.snapshot.fields.get(key) for key in ("店铺｜BD", *(f"L{i}" for i in range(8)), "店铺分配总计")}
                for row in summary_rows if row.snapshot.fields.get("店铺｜BD") == "等级数量总计"
            ]
        print(json.dumps(report, ensure_ascii=True, default=str))
    finally:
        await database.dispose()


if __name__ == "__main__":
    asyncio.run(run())
