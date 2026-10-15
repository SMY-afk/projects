import asyncio
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest

from erp_api.services.affiliate_capture_health import (
    AffiliateCaptureHealth,
    AffiliateCaptureHealthRepository,
)


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def get(self, key: str):
        return self.values.get(key)

    async def set(self, key: str, value: str, **_kwargs):
        self.values[key] = value


class RacingRedis(FakeRedis):
    def __init__(self) -> None:
        super().__init__()
        self.first_load_started = asyncio.Event()
        self.release_first_load = asyncio.Event()
        self.load_count = 0

    async def get(self, key: str):
        self.load_count += 1
        value = await super().get(key)
        if self.load_count == 1:
            self.first_load_started.set()
            await self.release_first_load.wait()
        return value


def test_health_transition_records_recovery_without_credentials() -> None:
    async def run():
        tenant_id = uuid4()
        shop_id = uuid4()
        redis = FakeRedis()
        repository = AffiliateCaptureHealthRepository(redis)
        blocked_at = datetime(2026, 8, 28, 1, tzinfo=UTC)
        recovered_at = blocked_at + timedelta(minutes=5)

        await repository.record(tenant_id, shop_id, "session_expired", now=blocked_at)
        health = await repository.record(tenant_id, shop_id, "online", now=recovered_at)
        return tenant_id, shop_id, redis, health

    tenant_id, shop_id, redis, health = asyncio.run(run())

    assert health.state == "online"
    assert health.recovered_at == datetime(2026, 8, 28, 1, 5, tzinfo=UTC)
    raw = next(iter(redis.values.values()))
    assert str(tenant_id) not in raw
    assert str(shop_id) not in raw
    assert "cookie" not in raw.casefold()
    assert "token" not in raw.casefold()


def test_missing_or_expired_health_is_reported_as_browser_offline() -> None:
    repository = AffiliateCaptureHealthRepository(FakeRedis())

    health = asyncio.run(repository.get(uuid4(), uuid4()))

    assert health.state == "browser_offline"
    assert health.cdp_available is False
    assert health.session_available is False


def test_health_preserves_the_latest_date_reported_by_tiktok() -> None:
    async def run():
        tenant_id = uuid4()
        shop_id = uuid4()
        repository = AffiliateCaptureHealthRepository(FakeRedis())
        observed = date(2026, 8, 29)

        await repository.record(
            tenant_id,
            shop_id,
            "online",
            latest_available_date=observed,
            latest_available_dates={
                "creators": observed,
                "videos": date(2026, 8, 27),
            },
            now=datetime(2026, 8, 31, 1, tzinfo=UTC),
        )
        return await repository.record(
            tenant_id,
            shop_id,
            "online",
            now=datetime(2026, 8, 31, 1, 0, 10, tzinfo=UTC),
        )

    health = asyncio.run(run())

    assert health.latest_available_date == date(2026, 8, 29)
    assert health.date_for("creators") == date(2026, 8, 29)
    assert health.date_for("videos") == date(2026, 8, 27)
    assert health.as_dict()["latestAvailableDate"] == "2026-08-29"
    assert health.as_dict()["latestAvailableDates"] == {
        "creators": "2026-08-29",
        "videos": "2026-08-27",
    }


def test_concurrent_heartbeat_cannot_erase_detected_resource_dates() -> None:
    async def run():
        tenant_id = uuid4()
        shop_id = uuid4()
        redis = RacingRedis()
        repository = AffiliateCaptureHealthRepository(redis)
        heartbeat = asyncio.create_task(repository.record(tenant_id, shop_id, "online"))
        await redis.first_load_started.wait()
        availability = asyncio.create_task(
            repository.record(
                tenant_id,
                shop_id,
                "online",
                latest_available_dates={"videos": date(2026, 9, 17)},
            )
        )
        await asyncio.sleep(0)
        redis.release_first_load.set()
        await asyncio.gather(heartbeat, availability)
        return await repository.get(tenant_id, shop_id)

    health = asyncio.run(run())

    assert health.date_for("videos") == date(2026, 9, 17)


def test_resource_date_does_not_fall_back_to_another_resources_date() -> None:
    health = AffiliateCaptureHealth(
        state="online",
        cdp_available=True,
        session_available=True,
        updated_at=datetime(2026, 9, 8, tzinfo=UTC),
        latest_available_date=date(2026, 9, 6),
        latest_available_dates={"creators": date(2026, 9, 6)},
    )

    assert health.date_for("videos") is None


def test_health_is_isolated_by_tenant_and_shop() -> None:
    async def run():
        tenant_id = uuid4()
        first_shop_id = uuid4()
        second_shop_id = uuid4()
        redis = FakeRedis()
        repository = AffiliateCaptureHealthRepository(redis)

        await repository.record(
            tenant_id,
            first_shop_id,
            "online",
            latest_available_date=date(2026, 8, 29),
        )
        await repository.record(tenant_id, second_shop_id, "session_expired")
        return (
            await repository.get(tenant_id, first_shop_id),
            await repository.get(tenant_id, second_shop_id),
            set(redis.values),
        )

    first, second, keys = asyncio.run(run())

    assert first.state == "online"
    assert first.latest_available_date == date(2026, 8, 29)
    assert second.state == "session_expired"
    assert len(keys) == 2


def test_verified_tk_date_is_reusable_during_same_shift() -> None:
    async def run():
        tenant_id, shop_id = uuid4(), uuid4()
        repository = AffiliateCaptureHealthRepository(FakeRedis())
        observed_at = datetime(2026, 10, 5, 0, tzinfo=UTC)
        await repository.record_observation(
            tenant_id, shop_id, "creators", date(2026, 10, 3), now=observed_at
        )
        await repository.record(
            tenant_id,
            shop_id,
            "online",
            latest_available_dates={"creators": date(2026, 10, 3)},
            now=observed_at + timedelta(hours=5),
        )
        return (
            await repository.observed_date_for(
                tenant_id, shop_id, "creators", now=observed_at + timedelta(hours=2)
            ),
            await repository.observed_date_for(
                tenant_id,
                shop_id,
                "creators",
                now=observed_at + timedelta(hours=6, minutes=1),
            ),
            await repository.observed_date_for(
                tenant_id, shop_id, "videos", now=observed_at + timedelta(minutes=1)
            ),
        )

    assert asyncio.run(run()) == (date(2026, 10, 3), None, None)


def test_verified_tk_observation_rejects_date_regression() -> None:
    async def run():
        tenant_id, shop_id = uuid4(), uuid4()
        repository = AffiliateCaptureHealthRepository(FakeRedis())
        now = datetime(2026, 10, 5, tzinfo=UTC)
        await repository.record_observation(
            tenant_id, shop_id, "videos", date(2026, 10, 3), now=now
        )
        with pytest.raises(ValueError, match="regressed"):
            await repository.record_observation(
                tenant_id,
                shop_id,
                "videos",
                date(2026, 10, 2),
                now=now + timedelta(minutes=1),
            )
        return await repository.observed_date_for(
            tenant_id, shop_id, "videos", now=now + timedelta(minutes=1)
        )

    assert asyncio.run(run()) == date(2026, 10, 3)
