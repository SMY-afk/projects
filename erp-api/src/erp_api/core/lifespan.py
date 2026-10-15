import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from arq.connections import RedisSettings, create_pool
from fastapi import FastAPI
from redis.asyncio import Redis

from erp_api.core.config import Settings
from erp_api.infrastructure.database import Database

logger = logging.getLogger("erp_api.lifecycle")


def create_lifespan(settings: Settings, database: Database, redis: Redis):
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        arq_queue = await create_pool(RedisSettings.from_dsn(settings.redis_url))
        app.state.arq_queue = arq_queue
        logger.info(
            "application_started",
            extra={"event": "application_started", "environment": settings.app_env},
        )
        try:
            yield
        finally:
            await arq_queue.aclose()
            await redis.aclose()
            await database.dispose()
            logger.info(
                "application_stopped",
                extra={"event": "application_stopped", "environment": settings.app_env},
            )

    return lifespan
