"""Read-only inventory of the ERP production database before restore."""

import argparse
import asyncio
import ssl
from pathlib import Path

import asyncpg

from scripts.check_rds_public_readonly import PUBLIC_HOST, load_rds_identity


async def main(progress_only: bool = False) -> None:
    username, password = load_rds_identity()
    context = ssl.create_default_context(
        cafile=str(Path("var/certs/ApsaraDB-CA-Chain.pem"))
    )
    context.verify_flags &= ~ssl.VERIFY_X509_STRICT
    connection = await asyncpg.connect(
        host=PUBLIC_HOST,
        port=5432,
        user=username,
        password=password,
        database="wj_erp",
        ssl=context,
        server_settings={"default_transaction_read_only": "on"},
    )
    try:
        if progress_only:
            size = await connection.fetchval("SELECT pg_database_size(current_database())")
            activity = await connection.fetch(
                "SELECT application_name, state, wait_event_type, wait_event, "
                "left(query, 90) AS query FROM pg_stat_activity "
                "WHERE datname=current_database() AND pid<>pg_backend_pid() "
                "ORDER BY application_name"
            )
            copy = await connection.fetch(
                "SELECT relid::regclass::text AS relation, bytes_processed, tuples_processed "
                "FROM pg_stat_progress_copy"
            )
            print(f"SIZE_BYTES={size} ACTIVITY={[tuple(r.values()) for r in activity]}")
            print(f"COPY_PROGRESS={[tuple(r.values()) for r in copy]}")
            return
        tables = await connection.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
        )
        nonempty = []
        for row in tables:
            name = row["tablename"]
            safe_name = name.replace('"', '""')
            count = await connection.fetchval(
                f'SELECT count(*) FROM public."{safe_name}"'
            )
            if count:
                nonempty.append((name, count))
        extensions = await connection.fetch(
            "SELECT e.extname, n.nspname FROM pg_extension e "
            "JOIN pg_namespace n ON n.oid=e.extnamespace ORDER BY e.extname"
        )
        active = await connection.fetch(
            "SELECT application_name, state, count(*) AS n FROM pg_stat_activity "
            "WHERE datname=current_database() AND pid<>pg_backend_pid() "
            "GROUP BY application_name,state ORDER BY application_name,state"
        )
        print(f"TABLES={len(tables)} NONEMPTY={nonempty}")
        print(f"EXTENSIONS={[(r['extname'], r['nspname']) for r in extensions]}")
        print(f"CONNECTIONS={[(r['application_name'], r['state'], r['n']) for r in active]}")
    finally:
        await connection.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--progress", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(progress_only=args.progress))
