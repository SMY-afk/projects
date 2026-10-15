from __future__ import annotations

import asyncio

from backend.app.services.sample_pipeline_busy_retry import retry_shop_sync_busy


def test_retry_shop_sync_busy_retries_persisted_batch_until_lock_releases() -> None:
    calls = 0
    delays: list[float] = []

    async def operation():
        nonlocal calls
        calls += 1
        if calls < 3:
            return {"feishu_deferred_reason": "shop_sync_busy"}
        return {"feishu_created": 1}

    async def sleep(delay: float) -> None:
        delays.append(delay)

    result = asyncio.run(
        retry_shop_sync_busy(
            operation,
            retry_seconds=20,
            max_wait_seconds=60,
            sleep=sleep,
        )
    )

    assert result == {"feishu_created": 1}
    assert calls == 3
    assert delays == [20, 20]


def test_retry_shop_sync_busy_stops_at_wait_budget() -> None:
    calls = 0

    async def operation():
        nonlocal calls
        calls += 1
        return {"feishu_deferred_reason": "shop_sync_busy"}

    async def sleep(_delay: float) -> None:
        return None

    result = asyncio.run(
        retry_shop_sync_busy(
            operation,
            retry_seconds=20,
            max_wait_seconds=40,
            sleep=sleep,
        )
    )

    assert result == {"feishu_deferred_reason": "shop_sync_busy"}
    assert calls == 3
