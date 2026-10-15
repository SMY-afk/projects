"""Restore the verified frozen ERP archive to the empty RDS production schema."""

import asyncio
import hashlib
import os
import ssl
import subprocess
import time
from pathlib import Path

import asyncpg

from scripts.check_rds_public_readonly import PUBLIC_HOST, load_rds_identity


ROOT = Path(__file__).resolve().parents[1]
BACKUP = ROOT / "var/backups/erp-source-cutover-20261009T120212.dump"
CA = ROOT / "var/certs/ApsaraDB-CA-Chain.pem"
EXPECTED_SHA256 = "a1b50b39bab1e50fad5ff8e64357b4732f3fe136070e3d9b4e67e8599d6ce789"
EXPECTED_SIZE = 627402477
EXPECTED_SEED = {"alembic_version": 1, "permissions": 11}


def check_archive() -> None:
    if BACKUP.stat().st_size != EXPECTED_SIZE:
        raise RuntimeError("BACKUP_SIZE_MISMATCH")
    with BACKUP.open("rb") as archive:
        digest = hashlib.file_digest(archive, "sha256").hexdigest()
    if digest != EXPECTED_SHA256:
        raise RuntimeError("BACKUP_SHA256_MISMATCH")
    print("BACKUP_SHA256_OK", flush=True)


def docker_env(username: str, password: str) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        PGHOST=PUBLIC_HOST,
        PGPORT="5432",
        PGUSER=username,
        PGPASSWORD=password,
        PGDATABASE="wj_erp",
        PGSSLMODE="verify-full",
        PGSSLROOTCERT="/rds-ca.pem",
        PGCONNECT_TIMEOUT="10",
        PGAPPNAME="erp_final_restore",
    )
    return env


def run_client(args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    command = [
        "docker", "run", "--rm", "--network", "bridge",
        "--mount", f"type=bind,source={CA},target=/rds-ca.pem,readonly",
        "--mount", f"type=bind,source={BACKUP},target=/backup.dump,readonly",
    ]
    for key in ("PGHOST", "PGPORT", "PGUSER", "PGPASSWORD", "PGDATABASE", "PGSSLMODE", "PGSSLROOTCERT", "PGCONNECT_TIMEOUT", "PGAPPNAME"):
        command.extend(("--env", key))
    command.extend(("postgres:17-alpine", *args))
    return subprocess.run(command, env=env, capture_output=True, text=True, timeout=30)


async def prepare_database(username: str, password: str) -> None:
    context = ssl.create_default_context(cafile=str(CA))
    context.verify_flags &= ~ssl.VERIFY_X509_STRICT
    connection = await asyncpg.connect(
        host=PUBLIC_HOST, port=5432, user=username, password=password,
        database="wj_erp", ssl=context,
        server_settings={"application_name": "erp_final_restore_prepare"},
    )
    try:
        async with connection.transaction():
            owner = await connection.fetchval(
                "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname=current_database()"
            )
            if owner != username:
                raise RuntimeError("TARGET_OWNER_MISMATCH")
            tables = await connection.fetch(
                "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
            )
            if len(tables) != 74:
                raise RuntimeError(f"TARGET_TABLE_COUNT_CHANGED={len(tables)}")
            nonempty = {}
            for row in tables:
                name = row["tablename"]
                safe_name = name.replace('"', '""')
                count = await connection.fetchval(f'SELECT count(*) FROM public."{safe_name}"')
                if count:
                    nonempty[name] = count
            if nonempty != EXPECTED_SEED:
                raise RuntimeError(f"TARGET_SEED_CHANGED={nonempty}")
            public_extensions = await connection.fetchval(
                "SELECT count(*) FROM pg_extension e JOIN pg_namespace n "
                "ON n.oid=e.extnamespace WHERE n.nspname='public'"
            )
            if public_extensions:
                raise RuntimeError("TARGET_PUBLIC_EXTENSION_PRESENT")
            print("TARGET_EMPTY_SEED_RECHECK_OK", flush=True)
            await connection.execute("DROP SCHEMA public CASCADE")
            await connection.execute("CREATE SCHEMA public AUTHORIZATION wj_erp")
        print("TARGET_PUBLIC_SCHEMA_REPLACED", flush=True)
    finally:
        await connection.close()


async def main() -> None:
    check_archive()
    username, password = load_rds_identity()
    env = docker_env(username, password)
    preflight = run_client(["psql", "-X", "-At", "-c", "SELECT current_database(), current_user, ssl FROM pg_stat_ssl WHERE pid=pg_backend_pid()"], env)
    if preflight.returncode != 0 or "wj_erp|" not in preflight.stdout or "|t" not in preflight.stdout:
        raise RuntimeError(f"DOCKER_PG_CLIENT_PREFLIGHT_FAILED: {preflight.stderr[-500:]}")
    print("DOCKER_PG_CLIENT_TLS_OK", flush=True)
    await prepare_database(username, password)
    command = [
        "docker", "run", "--rm", "--network", "bridge",
        "--mount", f"type=bind,source={CA},target=/rds-ca.pem,readonly",
        "--mount", f"type=bind,source={BACKUP},target=/backup.dump,readonly",
    ]
    for key in ("PGHOST", "PGPORT", "PGUSER", "PGPASSWORD", "PGDATABASE", "PGSSLMODE", "PGSSLROOTCERT", "PGCONNECT_TIMEOUT", "PGAPPNAME"):
        command.extend(("--env", key))
    command.extend(("postgres:17-alpine", "pg_restore", "--exit-on-error", "--no-owner", "--no-privileges", "--dbname=wj_erp", "/backup.dump"))
    log_path = ROOT / "var/backups/erp-rds-final-restore-20261009.log"
    print("RESTORE_STARTED_SINGLE_THREAD", flush=True)
    with log_path.open("w", encoding="utf-8") as output:
        process = subprocess.Popen(command, env=env, stdout=output, stderr=subprocess.STDOUT)
        started = time.monotonic()
        while process.poll() is None:
            await asyncio.sleep(20)
            print(f"RESTORE_RUNNING_SECONDS={int(time.monotonic() - started)}", flush=True)
        result = process.wait()
    if result:
        tail = log_path.read_text(encoding="utf-8", errors="replace")[-2000:]
        raise RuntimeError(f"RESTORE_FAILED_EXIT={result} LOG_TAIL={tail}")
    print(f"RESTORE_EXIT=0 ELAPSED_SECONDS={int(time.monotonic() - started)}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
