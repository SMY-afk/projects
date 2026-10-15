"""Read-only exact table and sequence comparison across frozen source and RDS."""

import argparse
import asyncio
import hashlib
import json
import ssl
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlsplit

import asyncpg

from erp_api.core.config import get_settings


PUBLIC_HOST = "pgm-wz9bb45790nb73dcso.pg.rds.aliyuncs.com"
PRIVATE_HOST = "pgm-wz9bb45790nb73dc.pg.rds.aliyuncs.com"
TABLES_OF_INTEREST = ("tenants", "users", "shops", "orders")


def credentials(raw: str) -> tuple[str, str, str]:
    parsed = urlsplit(raw)
    if not parsed.username or not parsed.password or not parsed.path:
        raise ValueError("DATABASE_IDENTITY_MISSING")
    return unquote(parsed.username), unquote(parsed.password), parsed.path.lstrip("/")


async def snapshot(connection: asyncpg.Connection, label: str) -> tuple[dict, list]:
    names = await connection.fetch(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
    )
    counts = {}
    for index, row in enumerate(names, 1):
        name = row["tablename"]
        quoted = name.replace('"', '""')
        counts[name] = await connection.fetchval(f'SELECT count(*) FROM public."{quoted}"')
        if index % 20 == 0 or index == len(names):
            print(f"{label}_COUNT_PROGRESS={index}/{len(names)}", flush=True)
    sequence_rows = await connection.fetch(
        "SELECT sequencename, last_value FROM pg_sequences "
        "WHERE schemaname = 'public' ORDER BY sequencename"
    )
    sequences = [(row["sequencename"], str(row["last_value"])) for row in sequence_rows]
    invalid = await connection.fetchval(
        "SELECT count(*) FROM pg_constraint "
        "WHERE connamespace = 'public'::regnamespace AND NOT convalidated"
    )
    count_hash = hashlib.sha256(
        json.dumps(sorted(counts.items()), separators=(",", ":")).encode()
    ).hexdigest()
    sequence_hash = hashlib.sha256(
        json.dumps(sequences, separators=(",", ":")).encode()
    ).hexdigest()
    selected = " ".join(f"{key}={counts.get(key)}" for key in TABLES_OF_INTEREST)
    print(
        f"{label}_SNAPSHOT TABLES={len(counts)} ROWS={sum(counts.values())} "
        f"COUNT_SHA256={count_hash} SEQUENCES={len(sequences)} "
        f"SEQUENCE_SHA256={sequence_hash} INVALID_CONSTRAINTS={invalid} {selected}",
        flush=True,
    )
    if invalid:
        raise ValueError("INVALID_CONSTRAINTS")
    return counts, sequences


def rds_url() -> str:
    result = subprocess.run(
        [
            "ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
            "-o", "ConnectTimeout=8", "erp-ecs",
            "grep '^DATABASE_URL=' /etc/erp/erp-api.env",
        ],
        capture_output=True,
        check=True,
        timeout=15,
    )
    line = result.stdout.decode().strip()
    if not line.startswith("DATABASE_URL="):
        raise ValueError("RDS_URL_MISSING")
    raw = line.split("=", 1)[1]
    if urlsplit(raw).hostname != PRIVATE_HOST:
        raise ValueError("RDS_PRIVATE_HOST_MISMATCH")
    return raw


async def main(mode: str, ca_path: Path) -> None:
    source_user, source_password, source_db = credentials(get_settings().database_url)
    source = await asyncpg.connect(
        host="127.0.0.1", port=5432, user=source_user,
        password=source_password, database=source_db, timeout=10,
        server_settings={"default_transaction_read_only": "on", "statement_timeout": "300000"},
    )
    try:
        source_data = await snapshot(source, "SOURCE")
    finally:
        await source.close()
    if mode == "source":
        return
    if not ca_path.is_file():
        raise ValueError("RDS_CA_MISSING")
    context = ssl.create_default_context(cafile=str(ca_path))
    context.verify_flags &= ~ssl.VERIFY_X509_STRICT
    target_user, target_password, target_db = credentials(rds_url())
    if target_db != "wj_erp":
        raise ValueError("RDS_TARGET_DB_MISMATCH")
    target = await asyncpg.connect(
        host=PUBLIC_HOST, port=5432, user=target_user,
        password=target_password, database=target_db, ssl=context, timeout=12,
        server_settings={"default_transaction_read_only": "on", "statement_timeout": "300000"},
    )
    try:
        target_data = await snapshot(target, "TARGET")
    finally:
        await target.close()
    if source_data != target_data:
        source_counts, source_sequences = source_data
        target_counts, target_sequences = target_data
        differences = [
            (name, source_counts.get(name), target_counts.get(name))
            for name in sorted(set(source_counts) | set(target_counts))
            if source_counts.get(name) != target_counts.get(name)
        ]
        print(f"COUNT_DIFFERENCES={differences} SEQUENCES_MATCH={source_sequences == target_sequences}")
        raise ValueError("SOURCE_TARGET_COUNT_OR_SEQUENCE_MISMATCH")
    print("CUTOVER_COUNTS_MATCH", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("source", "compare"), required=True)
    parser.add_argument("--ca", type=Path, default=Path("var/certs/ApsaraDB-CA-Chain.pem"))
    args = parser.parse_args()
    try:
        asyncio.run(main(args.mode, args.ca))
    except Exception as error:
        raise SystemExit(f"CUTOVER_COUNT_CHECK_FAILED TYPE={type(error).__name__}") from None
