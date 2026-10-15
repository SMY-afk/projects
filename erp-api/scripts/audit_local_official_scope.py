"""Read back only the approved local manifest, its assignments and receipts."""

import argparse
import asyncio
import json
from collections import Counter
from pathlib import Path

from sqlalchemy import text

from erp_api.core.config import get_settings
from erp_api.infrastructure.database import Database
from erp_api.main import build_sample_application_services
from erp_api.services.feishu_sample_change import parse_feishu_assignee
from erp_api.services.feishu_sample_record_snapshot import FeishuListedRecord
from erp_api.services.sample_business_readiness import SampleBusinessReadiness
from scripts.sample_watch_freshness import SHOPS, TENANT_ID


def cell(value):
    if isinstance(value, str):
        return value
    return "".join(x.get("text", "") for x in value) if isinstance(value, list) else ""


async def read_exact_records(client, record_ids):
    semaphore = asyncio.Semaphore(3)

    async def read(record_id):
        async with semaphore:
            return FeishuListedRecord(
                record_id, await client.get_record_snapshot(record_id)
            )

    return await asyncio.gather(*(read(record_id) for record_id in record_ids))


async def main(args):
    settings = get_settings()
    database = Database(settings.database_url)
    manifest = json.loads(Path(args.manifest).read_text())
    ids = [row["platform_application_id"] for row in manifest["rows"]]
    try:
        async with database.system_session_factory() as session:
            await session.execute(text("SET TRANSACTION READ ONLY"))
            rows = await session.execute(
                text("""
                SELECT a.platform_application_id,a.creator_username,a.is_current_projection,
                       a.platform_status,a.approve_expiration_at,w.feishu_record_id,
                       w.assigned_bd_name,w.processing_result,o.id outbox_id,o.status,
                       o.last_error_code,o.payload->>'assignment_record_id' assignment_record,
                       o.payload->>'message_id' private_message,o.payload->>'group_message_id' group_message,
                       o.sent_at,o.payload->>'source_event_id' source_event
                FROM sample_applications a JOIN sample_application_workflows w ON w.sample_application_id=a.id
                LEFT JOIN sample_notification_outbox o ON o.sample_application_id=a.id
                WHERE a.tenant_id=:tenant AND a.shop_id=:shop AND a.platform_application_id=ANY(:ids)
            """),
                {"tenant": TENANT_ID, "shop": SHOPS["local"], "ids": ids},
            )
            records = [dict(x) for x in rows.mappings()]
        current = [x for x in records if x["is_current_projection"]]
        new = [x for x in current if x["outbox_id"]]
        summary = {
            "target_applications": len(ids),
            "current_creator_groups": len(current),
            "grouped_child_applications": len(records) - len(current),
            "sample_records": sum(bool(x["feishu_record_id"]) for x in current),
            "assigned": sum(bool(x["assigned_bd_name"]) for x in current),
            "protected": sum(
                bool(x["processing_result"]) and not x["assigned_bd_name"]
                for x in current
            ),
            "notification_status": dict(Counter(x["status"] for x in new)),
            "private_receipts": sum(bool(x["private_message"]) for x in new),
            "group_receipts": sum(bool(x["group_message"]) for x in new),
            "persisted_assignment_records": sum(
                bool(x["assignment_record"]) for x in new
            ),
            "unfinished": [
                x["creator_username"]
                for x in current
                if not x["assigned_bd_name"] and not x["processing_result"]
            ],
        }
        if args.feishu:
            await SampleBusinessReadiness().require_ready(
                tenant_id=TENANT_ID, shop_id=SHOPS["local"]
            )
            services = build_sample_application_services(settings, database)
            sample = services["feishu_sample_client_router"].for_shop(SHOPS["local"])
            assignment = services["sample_assignment_record_service"]
            assignment = assignment.free if hasattr(assignment, "free") else assignment
            sample_snapshots = await read_exact_records(
                sample, {x["feishu_record_id"] for x in current}
            )
            assignment_snapshots = await read_exact_records(
                assignment._client, {x["assignment_record"] for x in new}
            )
            sample_map = {x.record_id: x.snapshot.fields for x in sample_snapshots}
            assignment_map = {
                x.record_id: x.snapshot.fields for x in assignment_snapshots
            }
            mismatches = []
            for row in current:
                fields = sample_map[row["feishu_record_id"]]
                if (
                    cell(fields.get("申请编号")) != row["platform_application_id"]
                    or cell(fields.get("达人账号")).lstrip("@").casefold()
                    != row["creator_username"].lstrip("@").casefold()
                ):
                    mismatches.append("sample_identity:" + row["creator_username"])
                if (
                    row["assigned_bd_name"]
                    and parse_feishu_assignee(fields.get("分配BD")).name
                    != row["assigned_bd_name"]
                ):
                    mismatches.append("sample_bd:" + row["creator_username"])
            for row in new:
                fields = assignment_map[row["assignment_record"]]
                if (
                    cell(fields.get("分配编号")) != str(row["outbox_id"])
                    or cell(fields.get("分配BD")) != row["assigned_bd_name"]
                    or cell(fields.get("通知状态")) != "已通知"
                ):
                    mismatches.append("assignment:" + row["creator_username"])
            summary["feishu_reread"] = {
                "sample_records": len(sample_map),
                "assignment_records": len(assignment_map),
                "mismatches": mismatches,
            }
        print(json.dumps(summary, ensure_ascii=False), flush=True)
        Path(args.output).write_text(
            json.dumps(
                {"summary": summary, "rows": records}, ensure_ascii=False, default=str
            )
        )
    finally:
        await database.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", default="/tmp/local-official-final-audit.json")
    parser.add_argument("--feishu", action="store_true")
    asyncio.run(main(parser.parse_args()))
