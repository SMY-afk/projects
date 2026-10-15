"""Read PostgreSQL and Redis evidence only; never call business APIs."""

import asyncio
import json
from datetime import UTC, datetime

from redis.asyncio import Redis
from sqlalchemy import text

from erp_api.core.config import get_settings
from erp_api.infrastructure.database import Database
from erp_api.services.affiliate_capture_health import AffiliateCaptureHealthRepository
from erp_api.services.sample_business_readiness import _valid_creator_batch_date
from scripts.sample_watch_freshness import SHOPS, TENANT_ID


async def main():
    settings = get_settings()
    database = Database(settings.database_url)
    redis = Redis.from_url(settings.redis_url)
    report = {"checked_at": datetime.now(UTC).isoformat()}
    try:
        async with database.system_session_factory() as session:
            await session.execute(text("SET TRANSACTION READ ONLY"))
            queries = {
                "notification_24h": """
                    SELECT s.shop_name, a.sample_type, o.status, o.last_error_code,
                           count(*) AS count, max(o.sent_at) AS last_sent_at
                    FROM sample_notification_outbox o
                    JOIN sample_applications a ON a.id=o.sample_application_id
                    JOIN shops s ON s.id=o.shop_id
                    WHERE o.tenant_id=:tenant AND o.created_at>now()-interval '24 hours'
                    GROUP BY 1,2,3,4 ORDER BY 1,2,3
                """,
                "assignment_24h": """
                    SELECT s.shop_name, a.sample_type, count(*) AS count,
                           max(e.occurred_at) AS last_assigned_at
                    FROM sample_application_events e
                    JOIN sample_applications a ON a.id=e.sample_application_id
                    JOIN shops s ON s.id=e.shop_id
                    WHERE e.tenant_id=:tenant AND e.event_type='bd_auto_assigned'
                      AND e.occurred_at>now()-interval '24 hours'
                    GROUP BY 1,2 ORDER BY 1,2
                """,
                "last_delivery_by_shop": """
                    SELECT s.shop_name, max(o.sent_at) AS last_sent_at,
                           count(*) FILTER (WHERE o.status IN
                               ('pending','processing','retry_wait','failed')) AS unfinished
                    FROM sample_notification_outbox o JOIN shops s ON s.id=o.shop_id
                    WHERE o.tenant_id=:tenant GROUP BY 1 ORDER BY 1
                """,
                "sync_failures_24h": """
                    SELECT s.shop_name, r.sync_type, r.error_code, count(*) AS count,
                           max(r.started_at) AS latest
                    FROM sample_sync_runs r JOIN shops s ON s.id=r.shop_id
                    WHERE r.tenant_id=:tenant AND r.status='failed'
                      AND r.started_at>now()-interval '24 hours'
                    GROUP BY 1,2,3 ORDER BY 1,2,3
                """,
                "unfinished_notifications": """
                    SELECT s.shop_name, a.sample_type, o.status, o.last_error_code,
                           count(*) AS count, max(o.updated_at) AS last_updated_at,
                           min(o.next_attempt_at) AS next_attempt_at
                    FROM sample_notification_outbox o
                    JOIN sample_applications a ON a.id=o.sample_application_id
                    JOIN shops s ON s.id=o.shop_id
                    WHERE o.tenant_id=:tenant
                      AND o.status IN ('pending','processing','retry_wait','failed')
                    GROUP BY 1,2,3,4 ORDER BY 1,2,3
                """,
            }
            for name, query in queries.items():
                rows = await session.execute(text(query), {"tenant": TENANT_ID})
                report[name] = [dict(row) for row in rows.mappings()]
        batch_date = _valid_creator_batch_date(datetime.now(UTC))
        report["required_daily_batch"] = batch_date.isoformat()
        successes = []
        async for key in redis.scan_iter(match="valid-creator-sync:*:success", count=30):
            key_text = key.decode() if isinstance(key, bytes) else key
            successes.append({"batch_date": key_text.split(":")[1], "ttl": await redis.ttl(key)})
        report["daily_success_receipts"] = successes
        report["daily_attempts"] = int(await redis.get(f"valid-creator-sync:{batch_date:%Y%m%d}:attempts") or 0)
        health_repository = AffiliateCaptureHealthRepository(redis)
        shops = []
        for label, shop_id in SHOPS.items():
            health = await health_repository.get(TENANT_ID, shop_id)
            observations = {}
            for resource in ("creators", "videos", "liveAccounts"):
                evidence = await health_repository.observed_evidence_for(TENANT_ID, shop_id, resource)
                observations[resource] = (
                    {"date": evidence[0].isoformat(), "observed_at": evidence[1].isoformat()}
                    if evidence else None
                )
            shops.append({"shop": label, "health": health.as_dict(), "observations": observations})
        report["capture_health"] = shops
        print(json.dumps(report, ensure_ascii=True, default=str))
    finally:
        await redis.aclose()
        await database.dispose()


if __name__ == "__main__":
    asyncio.run(main())
