"""Read-only probe for the isolated local ERP worker cutover environment."""

import asyncio
import os

import redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from scripts.cutover_runtime_env import build_environment


async def main() -> None:
    os.environ.update(build_environment())
    from erp_api.core.config import get_settings
    from erp_api.services.object_storage import S3ObjectStorage

    settings = get_settings()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            row = (
                await connection.execute(
                    text(
                        "SELECT current_database(), "
                        "(SELECT ssl FROM pg_stat_ssl WHERE pid=pg_backend_pid())"
                    )
                )
            ).one()
            if row[0] != "wj_erp" or row[1] is not True:
                raise RuntimeError("RDS_DATABASE_OR_TLS_MISMATCH")
        print("LOCAL_WORKER_RDS_TLS_OK", flush=True)
    finally:
        await engine.dispose()
    client = redis.Redis.from_url(settings.redis_url, socket_timeout=5)
    try:
        client.ping()
        print(f"LOCAL_WORKER_ECS_REDIS_OK SAMPLE_QUEUE={client.zcard('arq:sample')}", flush=True)
    finally:
        client.close()
    storage = S3ObjectStorage(
        endpoint_url=settings.object_storage_endpoint_url,
        region=settings.object_storage_region,
        access_key=settings.object_storage_access_key.get_secret_value(),
        secret_key=settings.object_storage_secret_key.get_secret_value(),
        bucket=settings.object_storage_bucket,
        force_path_style=settings.object_storage_force_path_style,
        key_prefix=settings.object_storage_key_prefix,
    )
    response = storage._client.list_objects_v2(
        Bucket=settings.object_storage_bucket,
        Prefix=settings.object_storage_key_prefix,
        MaxKeys=1,
    )
    if response.get("KeyCount", 0) < 1:
        raise RuntimeError("OSS_PREFIX_EMPTY")
    print("LOCAL_WORKER_OSS_READ_OK", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
