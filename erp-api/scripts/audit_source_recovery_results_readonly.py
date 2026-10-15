"""Read recovery receipts and business outcomes without exposing identities."""

import asyncio
import json
from datetime import UTC, datetime

from arq.connections import RedisSettings, create_pool
from arq.jobs import Job
from sqlalchemy import text

from erp_api.core.config import get_settings
from erp_api.infrastructure.database import Database
from scripts.sample_watch_freshness import TENANT_ID

QUERIES = {
    "assignments_since_recovery": """
        SELECT s.shop_name, a.sample_type, e.after_data->>'rule_version' AS rule_version,
               count(*) AS count, max(e.occurred_at) AS latest
        FROM sample_application_events e
        JOIN sample_applications a ON a.id=e.sample_application_id
        JOIN shops s ON s.id=e.shop_id
        WHERE e.tenant_id=:tenant AND e.event_type='bd_auto_assigned'
          AND e.occurred_at >= '2026-10-13T02:12:00Z'
        GROUP BY 1,2,3 ORDER BY 1,2,3
    """,
    "notifications_since_recovery": """
        SELECT s.shop_name, a.sample_type, o.status, o.last_error_code,
               count(*) AS count,
               count(*) FILTER (WHERE o.payload->>'message_id' IS NOT NULL) AS private_receipts,
               count(*) FILTER (WHERE o.payload->>'group_message_id' IS NOT NULL) AS group_receipts,
               max(o.sent_at) AS latest
        FROM sample_notification_outbox o
        JOIN sample_applications a ON a.id=o.sample_application_id
        JOIN shops s ON s.id=o.shop_id
        WHERE o.tenant_id=:tenant AND (o.created_at >= '2026-10-13T02:12:00Z'
          OR o.sent_at >= '2026-10-13T02:12:00Z')
        GROUP BY 1,2,3,4 ORDER BY 1,2,3
    """,
    "latest_block_reasons": """
        WITH latest AS (
            SELECT DISTINCT ON (e.sample_application_id)
                e.sample_application_id, e.shop_id, e.event_type, e.after_data
            FROM sample_application_events e
            WHERE e.tenant_id=:tenant
              AND e.event_type IN ('bd_auto_assigned','bd_auto_blocked')
            ORDER BY e.sample_application_id, e.occurred_at DESC
        )
        SELECT s.shop_name, a.sample_type, l.after_data->>'blocked_reason' AS reason,
               count(*) AS count
        FROM latest l JOIN sample_applications a ON a.id=l.sample_application_id
        JOIN shops s ON s.id=l.shop_id
        WHERE l.event_type='bd_auto_blocked' AND a.is_current_projection=TRUE
          AND (a.sample_type<>'free' OR (a.platform_status='PENDING'
            AND a.is_approvable=TRUE AND a.approve_expiration_at>now()))
        GROUP BY 1,2,3 ORDER BY 1,2,3
    """,
    "latest_sample_syncs": """
        SELECT DISTINCT ON (r.shop_id,r.sample_type,r.sync_type)
            s.shop_name,r.sample_type,r.sync_type,r.status,r.error_code,
            r.started_at,r.finished_at
        FROM sample_sync_runs r JOIN shops s ON s.id=r.shop_id
        WHERE r.tenant_id=:tenant
        ORDER BY r.shop_id,r.sample_type,r.sync_type,r.started_at DESC
    """,
}


async def main():
    settings = get_settings()
    database = Database(settings.database_url)
    redis = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    report = {"checked_at": datetime.now(UTC).isoformat(), "daily_jobs": []}
    try:
        async with database.system_session_factory() as session:
            await session.execute(text("SET TRANSACTION READ ONLY"))
            for name, query in QUERIES.items():
                rows = await session.execute(text(query), {"tenant": TENANT_ID})
                report[name] = [dict(row) for row in rows.mappings()]
        async for key in redis.scan_iter(match="arq:result:valid-creator-sync:20261012:*", count=20):
            key_text = key.decode() if isinstance(key, bytes) else key
            result = await Job(key_text.removeprefix("arq:result:"), redis).result_info()
            if result is None:
                continue
            item = {"success": result.success, "finished_at": result.finish_time}
            if isinstance(result.result, dict):
                allowed = ("status", "created", "updated", "deduplicated", "retained",
                           "final_records", "second_preview")
                item["apply"] = {name: result.result[name] for name in allowed if name in result.result}
            else:
                item["result_type"] = type(result.result).__name__
            report["daily_jobs"].append(item)
        report["sample_queue"] = await redis.zcard("arq:sample")
        report["daily_queue"] = await redis.zcard("arq:daily-valid-creators")
        report["daily_attempts"] = int(await redis.get("valid-creator-sync:20261012:attempts") or 0)
        report["daily_success_receipts"] = 0
        async for _ in redis.scan_iter(match="valid-creator-sync:20261012:*:success", count=20):
            report["daily_success_receipts"] += 1
        print(json.dumps(report, default=str))
    finally:
        await redis.aclose()
        await database.dispose()


if __name__ == "__main__":
    asyncio.run(main())
