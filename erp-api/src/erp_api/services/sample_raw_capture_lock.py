from __future__ import annotations

from contextlib import asynccontextmanager
from hashlib import blake2b
from uuid import UUID

from sqlalchemy import func, select


def sample_raw_capture_lock_key(tenant_id: UUID, shop_id: UUID) -> int:
    digest = blake2b(
        b"sample-raw-capture\0" + tenant_id.bytes + shop_id.bytes,
        digest_size=8,
    ).digest()
    return int.from_bytes(digest, byteorder="big", signed=True)


class SampleRawCaptureLock:
    """Hold one crash-safe PostgreSQL capture claim per tenant and shop."""

    def __init__(self, database) -> None:
        self._database = database

    @asynccontextmanager
    async def acquire(self, tenant_id: UUID, shop_id: UUID):
        lock_key = sample_raw_capture_lock_key(tenant_id, shop_id)
        async with self._database.engine.begin() as connection:
            acquired = await connection.scalar(
                select(func.pg_try_advisory_xact_lock(lock_key))
            )
            yield acquired is True
