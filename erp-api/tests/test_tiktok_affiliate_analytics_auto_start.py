import asyncio
import inspect
from datetime import date
from types import SimpleNamespace
from uuid import uuid4

from backend.app.services import (
    affiliate_capture_availability_startup as availability_startup,
)
from backend.app.services import tiktok_affiliate_capture_session as capture_session
from backend.app.services import tiktok_affiliate_intent_runner as intent_runner
from backend.app.services.affiliate_capture_health_monitor import (
    merge_latest_available_dates,
)
from backend.app.services.tiktok_affiliate_analytics_pager import (
    TikTokAffiliateAnalyticsPager,
)
from backend.app.services.tiktok_affiliate_analytics_run_state import (
    CaptureGuardConfig,
)
from backend.app.services.tiktok_affiliate_capture_session import (
    _detail_backfill_enabled,
    _is_intent_target,
    _refresh_completed_capture_dates,
    _run_next_intent,
)
from backend.app.services.tiktok_affiliate_capture_session import (
    run_capture_session as run_intent_capture_session,
)
from backend.app.services.tiktok_affiliate_intent_priority import (
    CREATOR_RUN_TIMEOUT_SECONDS,
)
from backend.app.services.tiktok_affiliate_intent_runner import (
    _finalize_intent_resource,
    _reconciled_video_snapshot,
)
from backend.app.services.tiktok_affiliate_listener import run_listener


class FakeCaptchaLocator:
    def __init__(self, page: "FakePage") -> None:
        self._page = page

    async def count(self) -> int:
        return 1 if self._page.captcha or self._page.hidden_captcha else 0

    def nth(self, index: int) -> "FakeCaptchaLocator":
        assert index == 0
        return self

    async def is_visible(self) -> bool:
        return self._page.captcha


class FakePage:
    def __init__(
        self,
        path: str,
        *,
        captcha: bool = False,
        hidden_captcha: bool = False,
    ) -> None:
        self.url = f"https://affiliate.tiktokshopglobalselling.com{path}"
        self.captcha = captcha
        self.hidden_captcha = hidden_captcha
        self.reload_count = 0

    def locator(self, selector: str) -> FakeCaptchaLocator:
        assert "captcha" in selector
        return FakeCaptchaLocator(self)

    async def reload(self, *, wait_until: str) -> None:
        assert wait_until == "domcontentloaded"
        self.reload_count += 1


def _pager(
    lock: asyncio.Lock, started_resources: set[str]
) -> TikTokAffiliateAnalyticsPager:
    return TikTokAffiliateAnalyticsPager(
        lock,
        guard_config=CaptureGuardConfig(min_request_interval_seconds=0),
        settle_delay_seconds=0,
        watchdog_interval_seconds=0,
        auto_started_resources=started_resources,
    )


def test_daemon_auto_starts_each_existing_target_resource_only_once() -> None:
    async def run() -> tuple[list[int], set[str]]:
        lock = asyncio.Lock()
        pages = [
            FakePage("/data/creator-analysis"),
            FakePage("/data/creator-analysis"),
            FakePage("/affiliate/assets/video-analysis"),
            FakePage("/home"),
        ]
        started_resources: set[str] = set()
        pager = _pager(lock, started_resources)

        await pager.start_open_pages_once(pages)  # type: ignore[arg-type]
        await pager.start_open_pages_once(pages)  # type: ignore[arg-type]
        return [page.reload_count for page in pages], started_resources

    assert asyncio.run(run()) == ([1, 0, 1, 0], {"creators", "videos"})


def test_daemon_does_not_auto_start_resource_again_after_reconnect() -> None:
    async def run() -> tuple[int, int]:
        started_resources: set[str] = set()
        first_page = FakePage("/data/creator-analysis")
        second_page = FakePage("/data/creator-analysis")
        await _pager(asyncio.Lock(), started_resources).start_open_pages_once(
            [first_page]  # type: ignore[list-item]
        )
        await _pager(asyncio.Lock(), started_resources).start_open_pages_once(
            [second_page]  # type: ignore[list-item]
        )
        return first_page.reload_count, second_page.reload_count

    assert asyncio.run(run()) == (1, 0)


def test_listener_restart_preserves_dates_from_slow_resources() -> None:
    assert merge_latest_available_dates(
        {"videos": date(2026, 8, 28)},
        {"creators": date(2026, 8, 29)},
    ) == {
        "creators": date(2026, 8, 29),
        "videos": date(2026, 8, 28),
    }


def test_capture_session_restores_missing_health_dates_from_complete_snapshots(
    monkeypatch,
) -> None:
    tenant_id = uuid4()
    shop_id = uuid4()

    class ReadRepository:
        def __init__(self, database) -> None:
            assert database == "database"

        async def latest_available_dates(self, actual_tenant_id, actual_shop_id):
            assert actual_tenant_id == tenant_id
            assert actual_shop_id == shop_id
            return {
                "creators": date(2026, 9, 12),
                "videos": date(2026, 9, 10),
            }

    class HealthRepository:
        async def get(self, actual_tenant_id, actual_shop_id):
            assert actual_tenant_id == tenant_id
            assert actual_shop_id == shop_id
            return SimpleNamespace(
                latest_available_dates={"videos": date(2026, 9, 9)}
            )

    monkeypatch.setattr(
        availability_startup,
        "AffiliateCenterReadRepository",
        ReadRepository,
    )

    result = asyncio.run(
        availability_startup.restore_capture_available_dates(
            "database",
            HealthRepository(),
            [],
            tenant_id,
            shop_id,
        )
    )

    assert result == {
        "creators": date(2026, 9, 12),
        "videos": date(2026, 9, 10),
    }


def test_capture_session_batch_size_is_bounded(monkeypatch) -> None:
    monkeypatch.delenv("AFFILIATE_CAPTURE_SESSION_BATCH_SIZE", raising=False)
    assert capture_session._capture_batch_size() == 1

    monkeypatch.setenv("AFFILIATE_CAPTURE_SESSION_BATCH_SIZE", "8")
    assert capture_session._capture_batch_size() == 8

    monkeypatch.setenv("AFFILIATE_CAPTURE_SESSION_BATCH_SIZE", "999")
    assert capture_session._capture_batch_size() == 20


def test_completed_capture_refreshes_persisted_resource_dates(monkeypatch) -> None:
    tenant_id = uuid4()
    shop_id = uuid4()
    records = []

    class Health:
        async def record(self, *args, **kwargs):
            records.append((args, kwargs))

    async def restore(*args, **kwargs):
        return {"creators": date(2026, 9, 15), "videos": date(2026, 9, 14)}

    monkeypatch.setattr(capture_session, "restore_capture_available_dates", restore)

    asyncio.run(
        _refresh_completed_capture_dates(
            object(), Health(), [], tenant_id, shop_id
        )
    )

    assert records == [
        (
            (tenant_id, shop_id, "online"),
            {
                "latest_available_date": date(2026, 9, 14),
                "latest_available_dates": {
                    "creators": date(2026, 9, 15),
                    "videos": date(2026, 9, 14),
                },
            },
        )
    ]


def test_daemon_auto_start_stops_on_existing_captcha_without_reload() -> None:
    async def run() -> tuple[int, dict[str, object]]:
        lock = asyncio.Lock()
        page = FakePage("/data/creator-analysis", captcha=True)
        pager = _pager(lock, set())

        await pager.start_open_pages_once([page])  # type: ignore[list-item]
        return page.reload_count, pager.resource_states["creators"]

    reload_count, state = asyncio.run(run())
    assert reload_count == 0
    assert state["status"] == "session_required"
    assert state["failure_category"] == "captcha"


def test_hidden_captcha_script_does_not_block_auto_start() -> None:
    async def run() -> tuple[int, dict[str, object]]:
        lock = asyncio.Lock()
        page = FakePage("/affiliate/assets/video-analysis", hidden_captcha=True)
        pager = _pager(lock, set())

        await pager.start_open_pages_once([page])  # type: ignore[list-item]
        return page.reload_count, pager.resource_states["videos"]

    reload_count, state = asyncio.run(run())
    assert reload_count == 1
    assert state["status"] == "idle"


def test_capture_session_polls_intents_before_registering_bounded_pager() -> None:
    session_source = inspect.getsource(run_intent_capture_session)
    intent_source = inspect.getsource(_run_next_intent)

    assert "_run_next_intent" in session_source
    assert "prepare_intent_page" in intent_source
    assert "TikTokAffiliateAnalyticsSynchronizer" in intent_source
    assert "TikTokAffiliateAnalyticsPager" in intent_source
    assert "build_affiliate_creator_capture" in intent_source
    assert "build_affiliate_video_capture" in intent_source
    assert "TikTokAffiliateCaptureDispatcher" in intent_source
    assert "page_persister=dispatcher.persist_page" in intent_source
    assert "terminal_handler=finalize" in intent_source
    assert "_is_intent_target" in intent_source
    assert intent_source.count("mutation_lock,") >= 2
    assert "max_pages=500" in intent_source
    assert "max_run_seconds=1800" in intent_source
    assert "_intent_timeout_seconds" in intent_source
    assert CREATOR_RUN_TIMEOUT_SECONDS == 1830.0
    assert "defer_session_blocked_intent" in intent_source
    assert "sync_creator_export" not in intent_source
    assert "start_open_pages_once" not in session_source


def test_intent_ignores_same_resource_responses_from_other_tabs() -> None:
    target_page = object()

    assert _is_intent_target(target_page, "creators", target_page, "creators")
    assert not _is_intent_target(object(), "creators", target_page, "creators")
    assert not _is_intent_target(target_page, "videos", target_page, "creators")


def test_page_persistence_failure_marks_claimed_intent_terminal() -> None:
    async def run():
        calls = []

        class Dispatcher:
            async def finalize_resource(self, resource, snapshot):
                calls.append(("finalize", resource, snapshot["status"]))

        class Repository:
            async def fail_intent(self, tenant_id, run_id, category):
                calls.append(("fail", tenant_id, run_id, category))

        tenant_id = uuid4()
        run_id = uuid4()
        await _finalize_intent_resource(
            Dispatcher(),
            Repository(),
            tenant_id,
            SimpleNamespace(resource="videos", run_id=run_id),
            "videos",
            {"status": "partial", "failure_category": "page_failed"},
        )
        return calls, tenant_id, run_id

    calls, tenant_id, run_id = asyncio.run(run())

    assert calls == [
        ("finalize", "videos", "partial"),
        ("fail", tenant_id, run_id, "request_timeout"),
    ]


def test_verified_video_total_drift_becomes_a_complete_snapshot(
    monkeypatch,
) -> None:
    async def verified(*_args) -> bool:
        return True

    monkeypatch.setattr(intent_runner, "verify_video_total_drift", verified)

    snapshot = asyncio.run(
        _reconciled_video_snapshot(
            object(),
            object(),
            "videos",
            {
                "status": "partial",
                "failure_category": "total_count_mismatch",
                "pages_fetched": 17,
                "records_unique": 332,
                "expected_total": 333,
            },
            object(),
            frozenset({"video-1"}),
        )
    )

    assert snapshot["status"] == "complete"
    assert snapshot["failure_category"] is None
    assert snapshot["terminal_reason"] == "verified_source_total_drift"


def test_listener_reconnects_without_owning_browser_credentials() -> None:
    source = inspect.getsource(run_listener)

    assert "run_capture_session" in source
    assert "discover_hubstudio_cdp_url" in source
    assert "browser_offline" in source
    assert "health_repository" in source
    assert "cookie" not in source.casefold()


def test_capture_session_keeps_health_alive_during_browser_preflight() -> None:
    source = inspect.getsource(run_intent_capture_session)

    heartbeat = source.index("run_connecting_health_heartbeat")
    browser_connect = source.index("connect_attached_hubstudio_browser")
    page_setup = source.index("ensure_affiliate_resource_pages")
    assert heartbeat < browser_connect
    assert heartbeat < page_setup
    preempt = source[source.index("preempt_tasks=") : source.index("),\n                )", source.index("preempt_tasks="))]
    assert "health_task" not in preempt
    assert "detail_backfill_task" in preempt
    assert "availability_task" in preempt


def test_creator_detail_backfill_can_be_disabled_for_video_only_runs(
    monkeypatch,
) -> None:
    monkeypatch.setenv("AFFILIATE_DETAIL_BACKFILL_ENABLED", "0")

    assert not _detail_backfill_enabled()


def test_creator_detail_backfill_remains_enabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("AFFILIATE_DETAIL_BACKFILL_ENABLED", raising=False)

    assert _detail_backfill_enabled()
