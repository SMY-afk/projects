import asyncio
from datetime import UTC, date, datetime
from uuid import UUID

import pytest

from backend.app.services import affiliate_capture_health_monitor as monitor
from erp_api.services.affiliate_capture_health import AffiliateCaptureHealth

TENANT_ID = UUID("6d0032eb-6a58-5a93-a819-d55c2a1c2e26")
SHOP_ID = UUID("fe629cb8-fa7b-56a5-970c-2f6e9ebc5703")


class FlakyRepository:
    def __init__(self, stopped: asyncio.Event) -> None:
        self.calls = 0
        self.states: list[str] = []
        self.stopped = stopped

    async def record(self, _tenant_id, _shop_id, state):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("temporary redis failure")
        self.states.append(state)
        self.stopped.set()


def test_online_heartbeat_retries_after_transient_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> FlakyRepository:
        stopped = asyncio.Event()
        repository = FlakyRepository(stopped)

        async def online(_contexts):
            return "online"

        monkeypatch.setattr(monitor, "browser_capture_state", online)
        await monitor.run_capture_health_heartbeat(
            [],
            TENANT_ID,
            SHOP_ID,
            repository,
            stopped,
            interval_seconds=0.001,
        )
        return repository

    repository = asyncio.run(run())

    assert repository.calls == 2
    assert repository.states == ["online"]


def test_connecting_heartbeat_retries_after_transient_failure() -> None:
    async def run() -> FlakyRepository:
        stopped = asyncio.Event()
        repository = FlakyRepository(stopped)
        await monitor.run_connecting_health_heartbeat(
            TENANT_ID,
            SHOP_ID,
            repository,
            stopped,
            interval_seconds=0.001,
        )
        return repository

    repository = asyncio.run(run())

    assert repository.calls == 2
    assert repository.states == ["connecting"]


def test_online_heartbeat_reports_connecting_when_page_probe_hangs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Repository:
        def __init__(self, stopped: asyncio.Event) -> None:
            self.states: list[str] = []
            self.stopped = stopped

        async def record(self, _tenant_id, _shop_id, state):
            self.states.append(state)
            self.stopped.set()

    async def run() -> Repository:
        stopped = asyncio.Event()
        repository = Repository(stopped)

        async def blocked(_contexts):
            await asyncio.Event().wait()

        monkeypatch.setattr(monitor, "browser_capture_state", blocked)
        await asyncio.wait_for(
            monitor.run_capture_health_heartbeat(
                [],
                TENANT_ID,
                SHOP_ID,
                repository,
                stopped,
                interval_seconds=0.001,
                operation_timeout_seconds=0.001,
            ),
            timeout=0.05,
        )
        return repository

    repository = asyncio.run(run())

    assert repository.states == ["connecting"]


def test_unrelated_login_tab_does_not_expire_valid_affiliate_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Page:
        def __init__(self, url: str) -> None:
            self.url = url

    class Context:
        def __init__(self) -> None:
            self.pages = [
                Page(
                    "https://affiliate.tiktokshopglobalselling.com/"
                    "data/creator-analysis?shop_id=shop-7"
                ),
                Page("https://partner-sso-us.tiktok.com/account/login"),
            ]

    async def security_failure(page: Page):
        if page.url.endswith("/account/login"):
            return "session_required", "session_expired"
        return None

    monkeypatch.setattr(monitor, "page_security_failure", security_failure)

    state = asyncio.run(monitor.browser_capture_state([Context()]))

    assert state == "online"


def test_hanging_dom_probe_does_not_block_browser_health(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Page:
        url = (
            "https://affiliate.tiktokshopglobalselling.com/"
            "data/creator-analysis?shop_id=shop-7"
        )

    class Context:
        def __init__(self) -> None:
            self.pages = [Page()]

    async def blocked(_page: Page):
        await asyncio.Event().wait()

    monkeypatch.setattr(monitor, "page_security_failure", blocked)

    state = asyncio.run(
        asyncio.wait_for(
            monitor.browser_capture_state(
                [Context()],
                page_probe_timeout_seconds=0.001,
            ),
            timeout=0.05,
        )
    )

    assert state == "connecting"


def test_sample_captcha_is_not_hidden_by_analytics_page(monkeypatch):
    from types import SimpleNamespace

    pages = [SimpleNamespace(url="https://affiliate.tiktokshopglobalselling.com/data/creator-analysis"),
             SimpleNamespace(url="https://affiliate.tiktokshopglobalselling.com/affiliate/sample/sample-request")]

    async def security(page):
        return ("session_required", "captcha") if "sample-request" in page.url else None

    monkeypatch.setattr(monitor, "page_security_failure", security)
    assert asyncio.run(monitor.browser_capture_state([SimpleNamespace(pages=pages)])) == "captcha"


class AvailabilityRepository:
    def __init__(self, stopped: asyncio.Event) -> None:
        self.stopped = stopped
        self.records: list[dict[str, object]] = []
        self.current = AffiliateCaptureHealth(
            state="online",
            cdp_available=True,
            session_available=True,
            updated_at=datetime(2026, 9, 8, tzinfo=UTC),
            latest_available_date=date(2026, 9, 5),
            latest_available_dates={
                "creators": date(2026, 9, 5),
                "videos": date(2026, 9, 5),
            },
        )

    async def get(self, _tenant_id, _shop_id):
        return self.current

    async def record(self, _tenant_id, _shop_id, state, **values):
        self.records.append({"state": state, **values})
        self.stopped.set()

    async def record_observation(self, _tenant_id, _shop_id, resource, day):
        self.records.append({"observation": resource, "day": day})


def test_availability_refresh_keeps_creator_result_when_video_probe_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> tuple[AvailabilityRepository, list[tuple[str, dict]]]:
        stopped = asyncio.Event()
        repository = AvailabilityRepository(stopped)
        logs = []

        async def detector(_contexts, resources):
            if len(resources) != 1:
                stopped.set()
                raise AssertionError("availability resources must be isolated")
            if resources == ("creators",):
                return {"creators": date(2026, 9, 6)}
            raise RuntimeError("video picker timed out")

        async def online(_contexts):
            return "online"

        monkeypatch.setattr(monitor, "browser_capture_state", online)
        monkeypatch.setattr(
            monitor,
            "_log",
            lambda event, **values: logs.append((event, values)),
        )
        await monitor.run_capture_availability_refresh(
            [],
            TENANT_ID,
            SHOP_ID,
            repository,
            stopped,
            asyncio.Lock(),
            interval_seconds=0.001,
            detector=detector,
        )
        return repository, logs

    repository, logs = asyncio.run(run())

    assert repository.records[0]["latest_available_dates"] == {
        "creators": date(2026, 9, 6),
        "videos": date(2026, 9, 5),
    }
    assert logs == [
        (
            "affiliate_availability_refresh_failed",
            {
                "tenant_id": TENANT_ID,
                "shop_id": SHOP_ID,
                "resource": "videos",
                "error_type": "RuntimeError",
            },
        )
    ]


def test_availability_refresh_logs_each_missing_resource(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> list[tuple[str, dict]]:
        stopped = asyncio.Event()
        repository = AvailabilityRepository(stopped)
        logs = []

        async def detector(_contexts, resources):
            if len(resources) != 1:
                stopped.set()
                return {}
            if resources == ("videos",):
                stopped.set()
            return {}

        monkeypatch.setattr(
            monitor,
            "_log",
            lambda event, **values: logs.append((event, values)),
        )
        await monitor.run_capture_availability_refresh(
            [],
            TENANT_ID,
            SHOP_ID,
            repository,
            stopped,
            asyncio.Lock(),
            interval_seconds=0.001,
            detector=detector,
        )
        return logs

    logs = asyncio.run(run())

    assert [values["resource"] for _event, values in logs] == ["creators", "videos"]
    assert {event for event, _values in logs} == {
        "affiliate_availability_refresh_missing"
    }


def test_availability_dates_never_regress() -> None:
    assert monitor.merge_latest_available_dates(
        {"creators": date(2026, 9, 6), "videos": date(2026, 9, 5)},
        {"creators": date(2026, 9, 5), "videos": date(2026, 9, 6)},
    ) == {
        "creators": date(2026, 9, 6),
        "videos": date(2026, 9, 6),
    }
