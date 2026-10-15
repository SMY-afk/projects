import asyncio

import pytest

from backend.app.services.tiktok_affiliate_creator_concurrency import (
    run_creator_workers,
)
from backend.app.services.tiktok_affiliate_creator_detail_backfill_factory import (
    _affiliate_concurrency,
    _affiliate_stale_hours,
)


def test_creator_workers_never_exceed_configured_concurrency() -> None:
    active = 0
    peak = 0

    async def process(value: int) -> int:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return value

    results = asyncio.run(run_creator_workers(range(20), process, concurrency=5))

    assert sorted(results) == list(range(20))
    assert peak == 5


def test_creator_workers_retry_429_with_exponential_backoff() -> None:
    attempts = 0
    delays: list[float] = []

    async def process(_value: int) -> int:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise RuntimeError("http_429")
        return 7

    async def sleep(delay: float) -> None:
        delays.append(delay)

    results = asyncio.run(
        run_creator_workers(
            [1],
            process,
            concurrency=1,
            max_attempts=4,
            backoff_base_seconds=1.0,
            sleep=sleep,
        )
    )

    assert results == [7]
    assert attempts == 3
    assert delays == [1.0, 2.0]


def test_creator_workers_do_not_retry_non_rate_limit_failures() -> None:
    attempts = 0

    async def process(_value: int) -> int:
        nonlocal attempts
        attempts += 1
        raise RuntimeError("session_expired")

    results = asyncio.run(run_creator_workers([1], process, concurrency=1))

    assert results == [None]
    assert attempts == 1


def test_affiliate_concurrency_defaults_to_five_and_is_bounded(monkeypatch) -> None:
    monkeypatch.delenv("AFFILIATE_CONCURRENCY", raising=False)
    assert _affiliate_concurrency() == 5

    monkeypatch.setenv("AFFILIATE_CONCURRENCY", "1000")
    assert _affiliate_concurrency() == 20

    monkeypatch.setenv("AFFILIATE_CONCURRENCY", "0")
    assert _affiliate_concurrency() == 1


def test_affiliate_stale_hours_must_be_positive(monkeypatch) -> None:
    monkeypatch.delenv("AFFILIATE_CREATOR_STALE_HOURS", raising=False)
    assert _affiliate_stale_hours() == 24

    monkeypatch.setenv("AFFILIATE_CREATOR_STALE_HOURS", "0")
    with pytest.raises(ValueError, match="must be positive"):
        _affiliate_stale_hours()
