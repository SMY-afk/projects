"""Verify the RDS public endpoint with ECS-held credentials, without writing data."""

import argparse
import asyncio
import os
import ssl
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlsplit

import asyncpg
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import create_async_engine


PUBLIC_HOST = "pgm-wz9bb45790nb73dcso.pg.rds.aliyuncs.com"
PRIVATE_HOST = "pgm-wz9bb45790nb73dc.pg.rds.aliyuncs.com"
DATABASES = ("wj_erp", "wj_erp_import_20261007")
TABLES = ("tenants", "users", "shops", "orders")


def load_rds_identity() -> tuple[str, str]:
    result = subprocess.run(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=yes",
            "-o",
            "ConnectTimeout=8",
            "erp-ecs",
            "grep '^DATABASE_URL=' /etc/erp/erp-api.env",
        ],
        capture_output=True,
        check=True,
        timeout=15,
    )
    lines = result.stdout.decode("utf-8").splitlines()
    if len(lines) != 1 or not lines[0].startswith("DATABASE_URL="):
        raise ValueError("RDS_DATABASE_URL_UNAVAILABLE")
    raw = lines[0].split("=", 1)[1].strip().strip("\"'")
    parsed = urlsplit(raw)
    if parsed.hostname != PRIVATE_HOST or parsed.port not in (None, 5432):
        raise ValueError("RDS_PRIVATE_HOST_MISMATCH")
    if not parsed.username or not parsed.password:
        raise ValueError("RDS_CREDENTIALS_MISSING")
    return unquote(parsed.username), unquote(parsed.password)


async def check_database(
    name: str, username: str, password: str, context: ssl.SSLContext
) -> None:
    connection = await asyncpg.connect(
        host=PUBLIC_HOST,
        port=5432,
        user=username,
        password=password,
        database=name,
        ssl=context,
        timeout=12,
        server_settings={
            "application_name": "codex_rds_readonly_preflight",
            "default_transaction_read_only": "on",
            "statement_timeout": "5000",
        },
    )
    try:
        ssl_state = await connection.fetchrow(
            "SELECT ssl, version FROM pg_stat_ssl WHERE pid = pg_backend_pid()"
        )
        if not ssl_state or not ssl_state["ssl"]:
            raise RuntimeError("RDS_TLS_NOT_ACTIVE")
        max_connections = await connection.fetchval("SHOW max_connections")
        active_connections = await connection.fetchval(
            "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()"
        )
        size_bytes = await connection.fetchval("SELECT pg_database_size(current_database())")
        database_owner = await connection.fetchval(
            "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = current_database()"
        )
        public_owner = await connection.fetchval(
            "SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname = 'public'"
        )
        public_tables = await connection.fetchval(
            "SELECT count(*) FROM pg_tables WHERE schemaname = 'public'"
        )
        counts = {}
        for table in TABLES:
            exists = await connection.fetchval("SELECT to_regclass($1)", f"public.{table}")
            counts[table] = (
                await connection.fetchval(f'SELECT count(*) FROM public."{table}"')
                if exists
                else None
            )
        print(
            f"RDS_READONLY_OK database={name} tls={ssl_state['version']} "
            f"max_connections={max_connections} active={active_connections} "
            f"size_bytes={size_bytes} db_owner={database_owner} "
            f"public_owner={public_owner} public_tables={public_tables} "
            + " ".join(f"{table}={counts[table]}" for table in TABLES)
        )
    finally:
        await connection.close()


async def main(ca_path: Path) -> None:
    if not ca_path.is_file():
        raise ValueError("RDS_CA_FILE_MISSING")
    context = ssl.create_default_context(cafile=str(ca_path))
    # ApsaraDB's CA bundle includes legacy non-critical Basic Constraints.
    # Keep certificate-chain and hostname validation; relax only X509_STRICT.
    context.verify_flags &= ~ssl.VERIFY_X509_STRICT
    username, password = load_rds_identity()
    for database in DATABASES:
        await check_database(database, username, password, context)
    os.environ["PGSSLMODE"] = "verify-full"
    os.environ["PGSSLROOTCERT"] = str(ca_path)
    url = URL.create(
        "postgresql+asyncpg",
        username=username,
        password=password,
        host=PUBLIC_HOST,
        port=5432,
        database="wj_erp_import_20261007",
    )
    engine = create_async_engine(url, pool_pre_ping=True, pool_size=1, max_overflow=0)
    try:
        async with engine.connect() as connection:
            name = (await connection.execute(text("SELECT current_database()"))).scalar_one()
            print(f"APPLICATION_DRIVER_SSL_OK database={name}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ca", type=Path, required=True)
    args = parser.parse_args()
    try:
        asyncio.run(main(args.ca))
    except Exception as error:
        print(f"RDS_READONLY_FAILED type={type(error).__name__}")
        raise SystemExit(1) from None
