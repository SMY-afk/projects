import asyncio
from datetime import UTC, date, datetime
from uuid import uuid4

from backend.app.services import affiliate_capture_health_monitor as monitor
from backend.app.services import tiktok_affiliate_available_date as available_date
from erp_api.services.affiliate_capture_health import AffiliateCaptureHealth


def test_resource_page_probe_has_its_own_timeout(monkeypatch) -> None:
    async def hanging_resource_page(*_args):
        await asyncio.Event().wait()

    monkeypatch.setattr(available_date, "_resource_page", hanging_resource_page)

    result = asyncio.run(
        asyncio.wait_for(
            available_date.detect_latest_selectable_dates(
                [],
                resources=("creators",),
                resource_timeout_seconds=0.001,
            ),
            timeout=0.05,
        )
    )

    assert result == {}


def test_initial_detection_only_probes_missing_resources() -> None:
    calls = []

    async def detector(_contexts, resources):
        calls.append(resources)
        return {resources[0]: date(2026, 9, 12)}

    result = asyncio.run(
        monitor.detect_initial_selectable_dates(
            [],
            resources=("creators",),
            detector=detector,
        )
    )

    assert calls == [("creators",)]
    assert result == {"creators": date(2026, 9, 12)}


def test_initial_detection_retries_a_missing_live_resource() -> None:
    calls = []

    async def detector(_contexts, resources):
        calls.append(resources)
        if len(calls) == 1:
            return {}
        return {resources[0]: date(2026, 9, 19)}

    result = asyncio.run(
        monitor.detect_initial_selectable_dates(
            [],
            resources=("creators",),
            retry_delay_seconds=0,
            detector=detector,
        )
    )

    assert calls == [("creators",), ("creators",)]
    assert result == {"creators": date(2026, 9, 19)}


def test_availability_refresh_retries_one_transient_timeout(monkeypatch) -> None:
    calls = []
    logs = []

    class Repository:
        def __init__(self, stopped):
            self.stopped = stopped
            self.records = []
            self.current = AffiliateCaptureHealth(
                state="online",
                cdp_available=True,
                session_available=True,
                updated_at=datetime(2026, 9, 11, tzinfo=UTC),
                latest_available_date=date(2026, 9, 7),
                latest_available_dates={"creators": date(2026, 9, 7)},
            )

        async def get(self, _tenant_id, _shop_id):
            return self.current

        async def record(self, _tenant_id, _shop_id, state, **values):
            self.records.append({"state": state, **values})
            self.stopped.set()

        async def record_observation(self, _tenant_id, _shop_id, resource, day):
            self.records.append({"observation": resource, "day": day})

    async def run():
        stopped = asyncio.Event()
        repository = Repository(stopped)

        async def detector(_contexts, resources):
            calls.append(resources)
            if resources == ("creators",) and calls.count(resources) == 1:
                raise TimeoutError
            return {resources[0]: date(2026, 9, 9)}

        monkeypatch.setattr(
            monitor,
            "_log",
            lambda event, **values: logs.append((event, values)),
        )
        await monitor.run_capture_availability_refresh(
            [],
            uuid4(),
            uuid4(),
            repository,
            stopped,
            asyncio.Lock(),
            interval_seconds=0.001,
            resource_timeout_seconds=0.01,
            retry_delay_seconds=0,
            detector=detector,
        )
        return repository

    repository = asyncio.run(run())

    assert calls.count(("creators",)) == 2
    assert repository.records[0]["latest_available_dates"]["creators"] == date(
        2026, 9, 9
    )
    assert not any(
        event == "affiliate_availability_refresh_failed"
        and values.get("resource") == "creators"
        for event, values in logs
    )
