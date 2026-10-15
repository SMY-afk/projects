from __future__ import annotations

from datetime import date
from uuid import UUID


class AffiliateOfficialAvailabilityRepository:
    def __init__(self, redis, *, ttl_seconds: int = 86_400) -> None:
        self._redis = redis
        self._ttl_seconds = ttl_seconds

    async def get(self, tenant_id: UUID, shop_id: UUID) -> date | None:
        value = await self._redis.get(self._key(tenant_id, shop_id))
        try:
            if isinstance(value, bytes):
                value = value.decode("ascii")
            return date.fromisoformat(value) if value else None
        except (UnicodeDecodeError, ValueError):
            return None

    async def set(self, tenant_id: UUID, shop_id: UUID, value: date) -> None:
        await self._redis.set(
            self._key(tenant_id, shop_id),
            value.isoformat(),
            ex=self._ttl_seconds,
        )

    @staticmethod
    def _key(tenant_id: UUID, shop_id: UUID) -> str:
        return f"affiliate:official-latest:{tenant_id}:{shop_id}"
