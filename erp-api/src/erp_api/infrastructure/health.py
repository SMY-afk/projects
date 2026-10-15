import asyncio

from redis.asyncio import Redis
from sqlalchemy import text

from erp_api.infrastructure.database import Database
from erp_api.workers.sample_queue import SAMPLE_WORKER_HEALTH_KEY


async def probe_dependencies(
    database: Database,
    redis_url: str,
    *,
    sample_sync_enabled: bool = False,
) -> dict[str, str]:
    database_result, redis_result = await asyncio.gather(
        _probe_database(database, sample_sync_enabled=sample_sync_enabled),
        _probe_redis(redis_url, sample_sync_enabled=sample_sync_enabled),
    )
    dependencies = {
        "database": database_result[0],
        "redis": redis_result[0],
        "sample_sync_config": "ok" if sample_sync_enabled else "disabled",
        "sample_schema": database_result[1],
        "sample_worker": redis_result[1],
    }
    return dependencies


async def _probe_database(
    database: Database, *, sample_sync_enabled: bool
) -> tuple[str, str]:
    try:
        async with database.engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
            schema_ready = (
                bool(await connection.scalar(text(_SAMPLE_SCHEMA_QUERY)))
                if sample_sync_enabled
                else False
            )
    except Exception:  # noqa: BLE001 -- readiness must collapse dependency failures
        return "unavailable", "unavailable" if sample_sync_enabled else "disabled"
    return "ok", "ok" if schema_ready else (
        "unavailable" if sample_sync_enabled else "disabled"
    )


async def _probe_redis(
    redis_url: str, *, sample_sync_enabled: bool
) -> tuple[str, str]:
    client = None
    try:
        client = Redis.from_url(redis_url)
        await client.ping()
        worker_ready = (
            bool(await client.exists(SAMPLE_WORKER_HEALTH_KEY))
            if sample_sync_enabled
            else False
        )
    except Exception:  # noqa: BLE001 -- readiness must collapse dependency failures
        return "unavailable", "unavailable" if sample_sync_enabled else "disabled"
    finally:
        if client is not None:
            await client.aclose()
    return "ok", "ok" if worker_ready else (
        "unavailable" if sample_sync_enabled else "disabled"
    )


_SAMPLE_SCHEMA_QUERY = """
SELECT
    to_regclass('public.sample_applications') IS NOT NULL
    AND to_regclass('public.sample_application_workflows') IS NOT NULL
    AND to_regclass('public.sample_application_events') IS NOT NULL
    AND to_regclass('public.sample_ingest_batches') IS NOT NULL
    AND to_regclass('public.sample_sync_runs') IS NOT NULL
    AND to_regclass('public.sample_notification_outbox') IS NOT NULL
"""
