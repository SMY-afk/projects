from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable


async def retry_shop_sync_busy(
    operation: Callable[[], Awaitable[dict[str, int | str]]],
    *,
    retry_seconds: float,
    max_wait_seconds: float,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> dict[str, int | str]:
    if retry_seconds <= 0 or max_wait_seconds < 0:
        raise ValueError("Retry timing must be positive.")
    waited = 0.0
    while True:
        result = await operation()
        if result.get("feishu_deferred_reason") != "shop_sync_busy":
            return result
        if waited + retry_seconds > max_wait_seconds:
            return result
        await sleep(retry_seconds)
        waited += retry_seconds
