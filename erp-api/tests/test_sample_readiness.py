from __future__ import annotations

import asyncio

from erp_api.infrastructure import health


class FakeConnection:
    def __init__(self, *, schema_ready: bool) -> None:
        self.schema_ready = schema_ready
        self.executed = []
        self.scalar_calls = 0

    async def execute(self, statement):
        self.executed.append(str(statement))

    async def scalar(self, statement):
        self.scalar_calls += 1
        self.executed.append(str(statement))
        return self.schema_ready


class ConnectionContext:
    def __init__(self, connection) -> None:
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, *_args):
        return None


class FakeDatabase:
    def __init__(self, connection) -> None:
        self.engine = self
        self.connection = connection

    def connect(self):
        return ConnectionContext(self.connection)


class FakeRedis:
    def __init__(self, *, worker_ready: bool) -> None:
        self.worker_ready = worker_ready
        self.keys = []
        self.closed = False

    async def ping(self):
        return True

    async def exists(self, key):
        self.keys.append(key)
        return int(self.worker_ready)

    async def aclose(self):
        self.closed = True


def test_enabled_sample_readiness_checks_schema_and_worker_heartbeat(
    monkeypatch,
) -> None:
    connection = FakeConnection(schema_ready=True)
    redis = FakeRedis(worker_ready=True)
    monkeypatch.setattr(health.Redis, "from_url", lambda _url: redis)

    result = asyncio.run(
        health.probe_dependencies(
            FakeDatabase(connection),
            "redis://example.invalid",
            sample_sync_enabled=True,
        )
    )

    assert result == {
        "database": "ok",
        "redis": "ok",
        "sample_sync_config": "ok",
        "sample_schema": "ok",
        "sample_worker": "ok",
    }
    assert redis.keys == ["arq:sample:health-check"]
    assert "sample_sync_runs" in connection.executed[1]
    assert redis.closed is True


def test_missing_worker_heartbeat_is_current_unavailable_state(monkeypatch) -> None:
    redis = FakeRedis(worker_ready=False)
    monkeypatch.setattr(health.Redis, "from_url", lambda _url: redis)

    result = asyncio.run(
        health.probe_dependencies(
            FakeDatabase(FakeConnection(schema_ready=True)),
            "redis://example.invalid",
            sample_sync_enabled=True,
        )
    )

    assert result["database"] == "ok"
    assert result["sample_schema"] == "ok"
    assert result["sample_worker"] == "unavailable"


def test_disabled_sample_sync_skips_schema_and_worker_checks(monkeypatch) -> None:
    connection = FakeConnection(schema_ready=False)
    redis = FakeRedis(worker_ready=False)
    monkeypatch.setattr(health.Redis, "from_url", lambda _url: redis)

    result = asyncio.run(
        health.probe_dependencies(
            FakeDatabase(connection),
            "redis://example.invalid",
            sample_sync_enabled=False,
        )
    )

    assert result["database"] == "ok"
    assert result["redis"] == "ok"
    assert result["sample_sync_config"] == "disabled"
    assert result["sample_schema"] == "disabled"
    assert result["sample_worker"] == "disabled"
    assert connection.scalar_calls == 0
    assert redis.keys == []


def test_invalid_redis_configuration_is_reported_without_breaking_readyz_probe(
    monkeypatch,
) -> None:
    def invalid_redis_url(_url):
        raise ValueError("invalid redis url")

    monkeypatch.setattr(health.Redis, "from_url", invalid_redis_url)

    result = asyncio.run(
        health.probe_dependencies(
            FakeDatabase(FakeConnection(schema_ready=True)),
            "invalid",
            sample_sync_enabled=True,
        )
    )

    assert result["database"] == "ok"
    assert result["redis"] == "unavailable"
    assert result["sample_worker"] == "unavailable"
