"""Count current latest-window sample work without exposing creator data."""

import asyncio
import json

from sqlalchemy import bindparam, text

from erp_api.core.config import get_settings
from erp_api.infrastructure.database import Database
from scripts.sample_watch_freshness import SHOPS, TENANT_ID

QUERY = """
WITH latest AS (
  SELECT DISTINCT ON (shop_id, sample_type)
    id, shop_id, sample_type, expected_total, captured_total, finished_at
  FROM sample_ingest_batches
  WHERE tenant_id = :tenant AND status = 'complete'
  ORDER BY shop_id, sample_type, finished_at DESC
), receipt AS (
  SELECT sample_application_id,
    bool_or(status = 'sent' OR sent_at IS NOT NULL) AS sent,
    bool_or(status IN ('pending','retry_wait','processing')) AS due
  FROM sample_notification_outbox
  WHERE tenant_id = :tenant
  GROUP BY sample_application_id
)
SELECT l.shop_id, l.sample_type, a.platform_status,
  count(a.id) AS rows,
  count(*) FILTER (WHERE a.is_current_projection = TRUE) AS current_rows,
  count(*) FILTER (
    WHERE a.is_current_projection = TRUE AND a.is_approvable = TRUE
      AND a.approve_expiration_at > now()
  ) AS valid_unexpired,
  count(*) FILTER (
    WHERE a.is_current_projection = TRUE AND a.is_approvable = TRUE
      AND a.approve_expiration_at > now() AND w.feishu_record_id IS NULL
  ) AS missing_feishu,
  count(*) FILTER (
    WHERE a.is_current_projection = TRUE AND a.is_approvable = TRUE
      AND a.approve_expiration_at > now() AND w.assigned_bd_name IS NULL
  ) AS missing_assignment,
  count(*) FILTER (WHERE r.due = TRUE) AS due_notification,
  count(*) FILTER (WHERE r.sent = TRUE) AS sent_notification
FROM latest l
LEFT JOIN sample_applications a ON a.source_capture_id = l.id
LEFT JOIN sample_application_workflows w ON w.sample_application_id = a.id
LEFT JOIN receipt r ON r.sample_application_id = a.id
WHERE l.shop_id IN :shops
GROUP BY l.shop_id, l.sample_type, a.platform_status
ORDER BY l.shop_id, l.sample_type, a.platform_status
"""


async def main() -> None:
    database = Database(get_settings().database_url)
    try:
        async with database.system_session_factory() as session:
            await session.execute(text("SET TRANSACTION READ ONLY"))
            statement = text(QUERY).bindparams(bindparam("shops", expanding=True))
            result = await session.execute(
                statement,
                {"tenant": TENANT_ID, "shops": tuple(SHOPS.values())},
            )
            names = {str(shop_id): label for label, shop_id in SHOPS.items()}
            rows = []
            for row in result.mappings():
                item = dict(row)
                item["shop"] = names.get(str(item.pop("shop_id")))
                if item["shop"] is None:
                    continue
                rows.append(item)
            print(json.dumps(rows, default=str))
    finally:
        await database.dispose()


if __name__ == "__main__":
    asyncio.run(main())
