from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable

MAX_AFFILIATE_CONCURRENCY = 20


async def run_creator_workers[T, R](
    items: Iterable[T],
    process: Callable[[T], Awaitable[R]],
    *,
    concurrency: int,
    max_attempts: int = 4,
    backoff_base_seconds: float = 1.0,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> list[R | None]:
    if not 1 <= concurrency <= MAX_AFFILIATE_CONCURRENCY:
        raise ValueError(
            f"concurrency must be between 1 and {MAX_AFFILIATE_CONCURRENCY}."
        )
    if max_attempts < 1:
        raise ValueError("max_attempts must be positive.")
    pending = list(enumerate(items))
    results: list[R | None] = [None] * len(pending)
    iterator = iter(pending)
    iterator_lock = asyncio.Lock()
    semaphore = asyncio.Semaphore(concurrency)

    async def worker() -> None:
        while True:
            async with iterator_lock:
                try:
                    index, item = next(iterator)
                except StopIteration:
                    return
            async with semaphore:
                results[index] = await _run_with_backoff(
                    item,
                    process,
                    max_attempts=max_attempts,
                    backoff_base_seconds=backoff_base_seconds,
                    sleep=sleep,
                )

    workers = [
        asyncio.create_task(worker()) for _ in range(min(concurrency, len(pending)))
    ]
    if workers:
        await asyncio.gather(*workers)
    return results


async def _run_with_backoff[T, R](
    item: T,
    process: Callable[[T], Awaitable[R]],
    *,
    max_attempts: int,
    backoff_base_seconds: float,
    sleep: Callable[[float], Awaitable[None]],
) -> R | None:
    for attempt in range(max_attempts):
        try:
            return await process(item)
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 -- one creator is an isolation boundary
            if not _is_rate_limited(error) or attempt + 1 >= max_attempts:
                return None
            await sleep(min(backoff_base_seconds * (2**attempt), 30.0))
    return None


def _is_rate_limited(error: Exception) -> bool:
    category = getattr(error, "category", None)
    return category in {"http_429", "rate_limited"} or str(error) in {
        "http_429",
        "rate_limited",
    }
