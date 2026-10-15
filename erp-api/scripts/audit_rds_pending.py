"""Read-only count of pending ERP work in the restored RDS database."""

import asyncio
import ssl
from pathlib import Path

import asyncpg

from scripts.check_rds_public_readonly import PUBLIC_HOST, load_rds_identity


async def main() -> None:
    user, password = load_rds_identity()
    context = ssl.create_default_context(
        cafile=str(Path("var/certs/ApsaraDB-CA-Chain.pem"))
    )
    context.verify_flags &= ~ssl.VERIFY_X509_STRICT
    connection = await asyncpg.connect(
        host=PUBLIC_HOST, port=5432, user=user, password=password,
        database="wj_erp", ssl=context,
        server_settings={"default_transaction_read_only": "on"},
    )
    try:
        for table in (
            "sample_notification_outbox",
            "platform_fulfillment_outbox",
            "sample_sync_runs",
            "order_sync_runs",
        ):
            rows = await connection.fetch(
                f'SELECT status, count(*) AS n FROM public."{table}" '
                "GROUP BY status ORDER BY status"
            )
            print(f"{table.upper()}={[(r['status'], r['n']) for r in rows]}")
        due_sample = await connection.fetchval(
            "SELECT count(*) FROM public.sample_notification_outbox "
            "WHERE status IN ('pending','retry_wait') "
            "AND (next_attempt_at IS NULL OR next_attempt_at <= now())"
        )
        processing_sample = await connection.fetchval(
            "SELECT count(*) FROM public.sample_notification_outbox "
            "WHERE status='processing'"
        )
        print(f"SAMPLE_NOTIFICATION_DUE={due_sample} PROCESSING={processing_sample}")
        notification_recent = await connection.fetch(
            "SELECT date(sent_at AT TIME ZONE 'Asia/Shanghai') AS day, "
            "count(*) AS n FROM public.sample_notification_outbox "
            "WHERE status='sent' AND sent_at >= '2026-10-05'::timestamptz "
            "GROUP BY 1 ORDER BY 1"
        )
        print(f"RECENT_SAMPLE_SENT_BY_DAY={[(r['day'], r['n']) for r in notification_recent]}")
        profiles = await connection.fetch(
            "SELECT app_profile, count(*) AS n FROM public.shop_connections "
            "GROUP BY app_profile ORDER BY app_profile"
        )
        print(f"SHOP_APP_PROFILES={[(r['app_profile'], r['n']) for r in profiles]}")
        shops = await connection.fetch(
            "SELECT id, shop_name FROM public.shops ORDER BY shop_name"
        )
        print(f"SHOP_IDENTITIES={[(str(r['id']), r['shop_name']) for r in shops]}")
        target_profile = await connection.fetchval(
            "SELECT app_profile FROM public.shop_connections "
            "WHERE shop_id='6fdc5cdc-90da-5524-82f7-9b11746c5e10'::uuid"
        )
        print(f"FAILED_SHOP_APP_PROFILE={target_profile}")
        bestseller = await connection.fetch(
            "SELECT entity_type, time_slot, entry_count, is_stale, "
            "last_error_category, refreshed_at "
            "FROM public.bestseller_snapshots "
            "WHERE shop_id='6fdc5cdc-90da-5524-82f7-9b11746c5e10'::uuid "
            "AND reference_date='2026-10-07'::date "
            "ORDER BY entity_type, time_slot"
        )
        print(f"APP_301_BESTSELLER_SNAPSHOTS={len(bestseller)} "
              f"DETAILS={[tuple(r.values()) for r in bestseller]}")
        product_one_day = next(
            (r for r in bestseller if r["entity_type"] == "product" and r["time_slot"] == "1D"),
            None,
        )
        if product_one_day:
            print(f"APP_301_PRODUCT_1D_REFRESHED_AT={product_one_day['refreshed_at']}")
        finance = await connection.fetch(
            "SELECT status, entity_type, mode, fetched_count, written_count, "
            "error_code, error_summary, "
            "started_at, finished_at FROM public.finance_sync_runs "
            "WHERE shop_id='6fdc5cdc-90da-5524-82f7-9b11746c5e10'::uuid "
            "ORDER BY started_at DESC LIMIT 5"
        )
        for row in finance:
            summary = (row["error_summary"] or "").replace("\n", " ")[:300]
            print(
                "APP_301_FINANCE_RUN="
                f"{row['status']}|{row['entity_type']}|{row['mode']}|"
                f"fetched={row['fetched_count']}|written={row['written_count']}|"
                f"{row['error_code']}|{summary}|"
                f"{row['started_at']}|{row['finished_at']}"
            )
    finally:
        await connection.close()


if __name__ == "__main__":
    asyncio.run(main())
