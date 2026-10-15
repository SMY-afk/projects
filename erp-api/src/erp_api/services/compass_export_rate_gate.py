from __future__ import annotations

from hashlib import sha256


class CompassExportDeferred(RuntimeError):
    def __init__(self, retry_after_seconds: int) -> None:
        self.retry_after_seconds = max(1, retry_after_seconds)
        super().__init__(
            f"TikTok Compass export is deferred for {self.retry_after_seconds} seconds."
        )


class CompassExportRateGate:
    """Atomically spaces Compass exports by TikTok App profile."""

    def __init__(self, redis, *, interval_seconds: int = 3_600) -> None:
        if interval_seconds < 1:
            raise ValueError("Compass export interval must be positive.")
        self._redis = redis
        self._interval = interval_seconds

    async def acquire(self, app_profile: str) -> None:
        key = self._key(app_profile)
        acquired = await self._redis.set(
            key,
            "reserved",
            ex=self._interval,
            nx=True,
        )
        if acquired:
            return
        ttl = await self._redis.ttl(key)
        retry_after = ttl if isinstance(ttl, int) and ttl > 0 else self._interval
        raise CompassExportDeferred(retry_after)

    async def defer(self, app_profile: str, *, retry_after_seconds: int) -> None:
        await self._redis.set(
            self._key(app_profile),
            "throttled",
            ex=max(self._interval, retry_after_seconds),
        )

    @staticmethod
    def _key(app_profile: str) -> str:
        normalized = app_profile.strip().casefold()
        if not normalized:
            raise ValueError("TikTok App profile is required for Compass rate limiting.")
        digest = sha256(normalized.encode("utf-8")).hexdigest()[:24]
        return f"tiktok:compass-export-gate:{digest}"
