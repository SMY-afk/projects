from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from weakref import WeakKeyDictionary

from redis.asyncio import Redis
from redis.exceptions import RedisError

from erp_api.services.feishu_sample_errors import FeishuSampleError

FEISHU_API_QPS = 5
_INTERVAL_MS = 1000 // FEISHU_API_QPS + 20
_RATE_KEY = "erp:feishu:api-rate:global"
_ACQUIRE_SCRIPT = """
local now = redis.call('TIME')
local now_ms = now[1] * 1000 + math.floor(now[2] / 1000)
local key = KEYS[1]
local next_at = tonumber(redis.call('GET', key)) or 0
if now_ms < next_at then
    return next_at - now_ms
end
redis.call('SET', key, now_ms + tonumber(ARGV[1]), 'PX', tonumber(ARGV[1]) * 2)
return 0
"""


class FeishuRateLimiter:
    """Queue local callers and pace requests across processes through Redis."""

    def __init__(
        self,
        redis_url: str,
        *,
        redis_client: Redis | None = None,
        sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if not redis_url:
            raise ValueError("Feishu rate limiter requires a Redis URL.")
        self._redis = redis_client or Redis.from_url(redis_url)
        self._sleeper = sleeper
        self._queue = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._queue:
            while True:
                try:
                    wait_ms = await self._redis.eval(
                        _ACQUIRE_SCRIPT,
                        1,
                        _RATE_KEY,
                        _INTERVAL_MS,
                    )
                except RedisError:
                    raise FeishuSampleError(
                        "Feishu rate limiter is unavailable.",
                        error_code="rate_limiter_unavailable",
                    ) from None
                if not isinstance(wait_ms, int) or wait_ms < 0:
                    raise FeishuSampleError(
                        "Feishu rate limiter returned an invalid response.",
                        error_code="rate_limiter_invalid_response",
                    )
                if wait_ms == 0:
                    return
                await self._sleeper(wait_ms / 1000)


_shared_limiters: WeakKeyDictionary[
    asyncio.AbstractEventLoop, dict[str, FeishuRateLimiter]
] = WeakKeyDictionary()


def shared_feishu_rate_limiter(redis_url: str) -> FeishuRateLimiter:
    loop = asyncio.get_running_loop()
    by_url = _shared_limiters.setdefault(loop, {})
    limiter = by_url.get(redis_url)
    if limiter is None:
        limiter = FeishuRateLimiter(redis_url)
        by_url[redis_url] = limiter
    return limiter
