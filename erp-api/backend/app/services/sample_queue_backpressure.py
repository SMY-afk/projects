from __future__ import annotations

import asyncio


async def put_with_backpressure[T](queue: asyncio.Queue[T], item: T) -> None:
    """Wait for bounded capacity instead of dropping a captured response."""
    await queue.put(item)
