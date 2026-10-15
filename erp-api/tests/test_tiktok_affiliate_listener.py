import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.app.services import tiktok_affiliate_capture
from backend.app.services import tiktok_affiliate_listener as listener


class FakeDatabase:
    disposed = False

    async def dispose(self) -> None:
        self.disposed = True


class FakeRedis:
    closed = False

    async def aclose(self) -> None:
        self.closed = True


class FakeHealthRepository:
    def __init__(self, _redis) -> None:
        self.records = []

    async def record(self, tenant_id, shop_id, status) -> None:
        self.records.append((tenant_id, shop_id, status))


class FakeIntentRepository:
    def __init__(self, _database) -> None:
        pass

    async def next_queued(self, _tenant_id, _platform_shop_ids):
        return SimpleNamespace(run_id=uuid4(), job_id="affiliate-intent:manual")


def _patch_runtime(monkeypatch: pytest.MonkeyPatch):
    database = FakeDatabase()
    redis = FakeRedis()
    monkeypatch.setattr(
        listener,
        "get_settings",
        lambda: SimpleNamespace(database_url="db", redis_url="redis"),
    )
    monkeypatch.setattr(listener, "Database", lambda _url: database)
    monkeypatch.setattr(listener, "from_url", lambda *_args, **_kwargs: redis)
    monkeypatch.setattr(
        listener, "AffiliateCaptureHealthRepository", FakeHealthRepository
    )
    monkeypatch.setattr(
        listener, "AffiliateCaptureIntentRepository", FakeIntentRepository
    )

    async def sample_round_ready(*_args, **_kwargs):
        return True

    monkeypatch.setattr(listener, "sample_round_releases_affiliate", sample_round_ready)

    async def configured_shop_id(*_args):
        return "platform-shop-1"

    monkeypatch.setattr(listener, "_configured_platform_shop_id", configured_shop_id)
    monkeypatch.setattr(
        listener,
        "assert_erp_hubstudio_cdp_url",
        lambda cdp_url: cdp_url,
    )
    return database, redis


def test_listener_retries_three_times_with_bounded_backoff(monkeypatch) -> None:
    database, redis = _patch_runtime(monkeypatch)
    attempts = []
    sleeps = []

    async def discover(**_kwargs):
        return "http://127.0.0.1:9222"

    async def capture(*_args, **_kwargs):
        attempts.append(True)
        raise ConnectionError("cdp disconnected")

    async def sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr(listener, "discover_hubstudio_cdp_url", discover)
    monkeypatch.setattr(tiktok_affiliate_capture, "run_capture_session", capture)
    monkeypatch.setattr(listener.asyncio, "sleep", sleep)

    asyncio.run(
        listener.run_listener(
            "http://127.0.0.1:9222",
            uuid4(),
            uuid4(),
            retry_delays=(30.0, 60.0, 300.0),
        )
    )

    assert len(attempts) == 4
    assert sleeps == [30.0, 60.0, 300.0]
    assert database.disposed
    assert redis.closed


def test_listener_rediscovers_a_changed_cdp_after_disconnect(
    monkeypatch,
) -> None:
    _patch_runtime(monkeypatch)
    current_urls = []
    capture_urls = []

    async def discover(*, current_url, **kwargs):
        current_urls.append(current_url)
        assert "command_line_reader" not in kwargs
        return (
            "http://127.0.0.1:9222"
            if len(current_urls) == 1
            else "http://127.0.0.1:9333"
        )

    async def capture(cdp_url, *_args, **_kwargs):
        capture_urls.append(cdp_url)
        if len(capture_urls) == 1:
            return True
        raise asyncio.CancelledError

    async def sleep(_delay):
        return None

    monkeypatch.setattr(listener, "discover_hubstudio_cdp_url", discover)
    monkeypatch.setattr(tiktok_affiliate_capture, "run_capture_session", capture)
    monkeypatch.setattr(listener.asyncio, "sleep", sleep)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            listener.run_listener(
                "http://127.0.0.1:9222",
                uuid4(),
                uuid4(),
                retry_delays=(30.0, 60.0, 300.0),
            )
        )

    assert current_urls == ["http://127.0.0.1:9222"] * 2
    assert capture_urls == ["http://127.0.0.1:9222", "http://127.0.0.1:9333"]


def test_listener_revalidates_erp_ownership_before_every_connection(
    monkeypatch,
) -> None:
    _patch_runtime(monkeypatch)
    ownership_checks = []
    captures = []

    def assert_owned(cdp_url):
        ownership_checks.append(cdp_url)
        return cdp_url

    async def discover(*, current_url, **_kwargs):
        return current_url

    async def capture(*_args, **_kwargs):
        captures.append(True)
        if len(captures) == 1:
            return True
        raise asyncio.CancelledError

    async def sleep(_delay):
        return None

    monkeypatch.setattr(listener, "assert_erp_hubstudio_cdp_url", assert_owned)
    monkeypatch.setattr(listener, "discover_hubstudio_cdp_url", discover)
    monkeypatch.setattr(tiktok_affiliate_capture, "run_capture_session", capture)
    monkeypatch.setattr(listener.asyncio, "sleep", sleep)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            listener.run_listener(
                "http://127.0.0.1:9222",
                uuid4(),
                uuid4(),
                retry_delays=(30.0,),
            )
        )

    assert ownership_checks == ["http://127.0.0.1:9222"] * 2


def test_listener_discovers_cdp_for_the_configured_shop(monkeypatch) -> None:
    _patch_runtime(monkeypatch)
    discovery_calls = []

    async def discover(**kwargs):
        discovery_calls.append(kwargs)
        return "http://127.0.0.1:9444"

    async def capture(*_args, **_kwargs):
        raise asyncio.CancelledError

    monkeypatch.setattr(listener, "discover_hubstudio_cdp_url", discover)
    monkeypatch.setattr(tiktok_affiliate_capture, "run_capture_session", capture)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(listener.run_listener(None, uuid4(), uuid4(), retry_delays=()))

    assert discovery_calls[0]["current_url"] is None
    assert discovery_calls[0]["expected_platform_shop_id"] == "platform-shop-1"
    assert "command_line_reader" not in discovery_calls[0]


def test_listener_does_not_attach_playwright_while_capture_queue_is_empty(
    monkeypatch,
) -> None:
    _patch_runtime(monkeypatch)
    captures = []

    class EmptyIntentRepository:
        def __init__(self, _database) -> None:
            pass

        async def next_queued(self, _tenant_id, _platform_shop_ids):
            return None

    async def discover(**_kwargs):
        return "http://127.0.0.1:9222"

    async def capture(*_args, **_kwargs):
        captures.append(True)

    async def stop_after_idle_wait(_delay):
        raise asyncio.CancelledError

    monkeypatch.setattr(
        listener, "AffiliateCaptureIntentRepository", EmptyIntentRepository
    )
    monkeypatch.setattr(listener, "discover_hubstudio_cdp_url", discover)
    monkeypatch.setattr(listener, "daily_retry_window_open", lambda _now: False)
    monkeypatch.setattr(tiktok_affiliate_capture, "run_capture_session", capture)
    monkeypatch.setattr(listener.asyncio, "sleep", stop_after_idle_wait)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(listener.run_listener(None, uuid4(), uuid4(), retry_delays=()))

    assert captures == []


def test_listener_probes_real_dates_before_scheduling_window_collection(
    monkeypatch,
) -> None:
    _patch_runtime(monkeypatch)
    probes = []

    class EmptyIntentRepository:
        def __init__(self, _database) -> None:
            pass

        async def next_queued(self, _tenant_id, _platform_shop_ids):
            return None

    async def discover(**_kwargs):
        return "http://127.0.0.1:9222"

    async def probe(*args):
        probes.append(args)

    async def stop_after_idle_wait(_delay):
        raise asyncio.CancelledError

    monkeypatch.setattr(
        listener, "AffiliateCaptureIntentRepository", EmptyIntentRepository
    )
    monkeypatch.setattr(listener, "discover_hubstudio_cdp_url", discover)
    monkeypatch.setattr(listener, "daily_retry_window_open", lambda _now: True)
    monkeypatch.setattr(listener, "availability_probe_stagger_seconds", lambda _: 0)
    monkeypatch.setattr(listener, "_probe_idle_availability", probe)
    monkeypatch.setattr(listener.asyncio, "sleep", stop_after_idle_wait)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(listener.run_listener(None, uuid4(), uuid4(), retry_delays=()))

    assert len(probes) == 1
    assert probes[0][0] == "http://127.0.0.1:9222"


def test_listener_captures_manual_intent_outside_daily_window(
    monkeypatch,
) -> None:
    _patch_runtime(monkeypatch)
    captures = []

    async def discover(**_kwargs):
        return "http://127.0.0.1:9222"

    async def capture(*_args, **_kwargs):
        captures.append(True)
        raise asyncio.CancelledError

    class OutsideWindowClock:
        @staticmethod
        def now(_timezone):
            return datetime(2026, 9, 16, 12, 0, tzinfo=UTC)

    monkeypatch.setattr(listener, "datetime", OutsideWindowClock)
    monkeypatch.setattr(listener, "discover_hubstudio_cdp_url", discover)
    monkeypatch.setattr(tiktok_affiliate_capture, "run_capture_session", capture)

    async def stop_if_idle(_delay):
        raise asyncio.CancelledError

    monkeypatch.setattr(listener.asyncio, "sleep", stop_if_idle)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(listener.run_listener(None, uuid4(), uuid4(), retry_delays=()))

    assert captures == [True]


def test_listener_continues_scheduled_backlog_outside_daily_window(
    monkeypatch,
) -> None:
    _patch_runtime(monkeypatch)
    captures = []

    class ScheduledIntentRepository:
        def __init__(self, _database) -> None:
            pass

        async def next_queued(self, _tenant_id, _platform_shop_ids):
            return SimpleNamespace(
                run_id=uuid4(),
                job_id="affiliate-schedule:20260915:shop:creator:run",
            )

    async def discover(**_kwargs):
        return "http://127.0.0.1:9222"

    async def capture(*_args, **_kwargs):
        captures.append(True)
        raise asyncio.CancelledError

    monkeypatch.setattr(
        listener, "AffiliateCaptureIntentRepository", ScheduledIntentRepository
    )
    monkeypatch.setattr(listener, "discover_hubstudio_cdp_url", discover)
    monkeypatch.setattr(tiktok_affiliate_capture, "run_capture_session", capture)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(listener.run_listener(None, uuid4(), uuid4(), retry_delays=()))

    assert captures == [True]


def test_listener_waits_for_sample_round_before_affiliate_capture(
    monkeypatch,
) -> None:
    _patch_runtime(monkeypatch)
    captures = []

    async def sample_round_not_ready(*_args, **_kwargs):
        return False

    async def discover(**_kwargs):
        return "http://127.0.0.1:9222"

    async def capture(*_args, **_kwargs):
        captures.append(True)

    async def stop_after_idle_wait(_delay):
        raise asyncio.CancelledError

    monkeypatch.setattr(
        listener, "sample_round_releases_affiliate", sample_round_not_ready
    )
    monkeypatch.setattr(listener, "discover_hubstudio_cdp_url", discover)
    monkeypatch.setattr(tiktok_affiliate_capture, "run_capture_session", capture)
    monkeypatch.setattr(listener.asyncio, "sleep", stop_after_idle_wait)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(listener.run_listener(None, uuid4(), uuid4(), retry_delays=()))

    assert captures == []
