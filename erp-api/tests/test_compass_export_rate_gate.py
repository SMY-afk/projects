import pytest

from erp_api.services.compass_export_rate_gate import (
    CompassExportDeferred,
    CompassExportRateGate,
)


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, int] = {}

    async def set(self, key, value, *, ex, nx=False):
        if nx and key in self.values:
            return None
        self.values[key] = ex
        return True

    async def ttl(self, key):
        return self.values.get(key, -2)


@pytest.mark.asyncio
async def test_gate_allows_only_one_export_per_app_interval() -> None:
    redis = FakeRedis()
    gate = CompassExportRateGate(redis, interval_seconds=3_600)

    await gate.acquire("feifei")

    with pytest.raises(CompassExportDeferred) as caught:
        await gate.acquire("feifei")

    assert caught.value.retry_after_seconds == 3_600


@pytest.mark.asyncio
async def test_gate_isolates_different_app_profiles() -> None:
    redis = FakeRedis()
    gate = CompassExportRateGate(redis, interval_seconds=3_600)

    await gate.acquire("feifei")
    await gate.acquire("legacy")

    assert len(redis.values) == 2


@pytest.mark.asyncio
async def test_gate_refreshes_cooldown_after_platform_throttle() -> None:
    redis = FakeRedis()
    gate = CompassExportRateGate(redis, interval_seconds=3_600)

    await gate.acquire("feifei")
    await gate.defer("feifei", retry_after_seconds=7_200)

    with pytest.raises(CompassExportDeferred) as caught:
        await gate.acquire("feifei")

    assert caught.value.retry_after_seconds == 7_200
