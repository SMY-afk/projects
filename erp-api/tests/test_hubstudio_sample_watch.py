from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from backend.app.services.hubstudio_sample_watch import (
    SAMPLE_PAGE_PATH,
    _capture_profiles_then_sync,
    _CycleState,
    _load_first_page,
    _run_cycle,
    _sample_page_matches,
    _wait_for_processing,
)
from backend.app.services.sample_request_page_controls import (
    _select_request_date,
    _select_review_status,
    next_sample_page,
)


class FakeLocator:
    def __init__(
        self,
        count: int = 0,
        text: str = "",
        *,
        click_failures: int = 0,
        items: list[FakeLocator] | None = None,
        on_click=None,
        attributes: dict[str, str] | None = None,
    ) -> None:
        self._count = len(items) if items is not None else count
        self._text = text
        self._click_failures = click_failures
        self._items = items
        self._on_click = on_click
        self._attributes = attributes or {}
        self.clicks = 0
        self.click_kwargs: list[dict[str, object]] = []
        self.visible_filters = 0

    async def count(self) -> int:
        return self._count

    async def click(self, **kwargs) -> None:
        self.clicks += 1
        self.click_kwargs.append(kwargs)
        if self._click_failures:
            self._click_failures -= 1
            raise PlaywrightTimeoutError("option detached")
        if self._on_click is not None:
            self._on_click()

    async def inner_text(self) -> str:
        return self._text

    async def get_attribute(self, name: str) -> str | None:
        return self._attributes.get(name)

    def nth(self, index: int):
        return self._items[index] if self._items is not None else self

    def filter(self, *, visible: bool | None = None):
        assert visible is True
        self.visible_filters += 1
        return self


class FakePage:
    def __init__(self, url: str, next_count: int = 0) -> None:
        self.url = url
        self.goto_urls: list[str] = []
        self.reload_count = 0
        self.reload_failures = 0
        self.redirect_url: str | None = None
        self.closed = False
        self.wait_timeouts: list[float] = []
        self.next_locator = FakeLocator(next_count)
        self.review_locator = FakeLocator(1, attributes={"aria-selected": "true"})
        self.sort_locator = FakeLocator(1, "Relevancy")
        self.relevance_locator = FakeLocator(
            1,
            "Relevancy",
            on_click=lambda: setattr(self.sort_locator, "_text", "Relevancy"),
        )
        self.selected_date_locator = FakeLocator(0)
        self.date_locator = FakeLocator(
            1,
            "Application date",
            on_click=lambda: setattr(self.sort_locator, "_text", "Application date"),
        )
        self.comboboxes = FakeLocator(
            items=[
                FakeLocator(1, "Creator username"),
                FakeLocator(1, "All"),
                self.sort_locator,
            ]
        )

    async def goto(self, url: str, **_kwargs) -> None:
        self.goto_urls.append(url)
        self.url = self.redirect_url or url

    async def reload(self, **_kwargs) -> None:
        self.reload_count += 1
        if self.reload_failures:
            self.reload_failures -= 1
            raise PlaywrightTimeoutError("domcontentloaded timeout")
        if self.redirect_url is not None:
            self.url = self.redirect_url

    async def close(self) -> None:
        self.closed = True

    async def wait_for_timeout(self, timeout: float) -> None:
        self.wait_timeouts.append(timeout)

    def expect_response(self, _predicate, *, timeout: float):
        assert timeout in {5_000, 30_000}
        return FakeExpectedResponse()

    def locator(self, selector: str) -> FakeLocator:
        if selector == "li.core-pagination-item-next:not(.core-pagination-item-disabled)":
            return self.next_locator
        assert selector == ".core-select-view-value"
        return FakeLocator(items=[self.sort_locator])

    def get_by_role(self, role: str, *, name=None) -> FakeLocator:
        if role == "tab":
            assert name.search("To review 81")
            assert name.search("待审核 35")
            return self.review_locator
        if role == "combobox":
            assert name is None
            return self.comboboxes
        assert role == "option"
        if name.search("Relevancy"):
            return self.relevance_locator
        assert name.search("Application date")
        assert name.search("申请日期")
        assert name.search("Request date")
        return self.date_locator

    def get_by_text(self, name, *, exact: bool) -> FakeLocator:
        assert exact is True
        if name.search("Relevancy"):
            return self.sort_locator
        assert name.search("Application date")
        assert name.search("申请日期")
        assert name.search("Request date")
        return self.selected_date_locator


class FakeReviewResponse:
    async def finished(self) -> None:
        return None


class FakeExpectedResponse:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args) -> None:
        return None

    @property
    def value(self):
        async def resolve():
            return FakeReviewResponse()

        return resolve()


class FakeContext:
    def __init__(self, pages: list[FakePage]) -> None:
        self.pages = pages
        self.created = FakePage("about:blank")

    async def new_page(self) -> FakePage:
        self.pages.append(self.created)
        return self.created


class FakeListener:
    def __init__(self) -> None:
        self.is_stopped = False
        self.stop_reason = None
        self.stop_calls: list[str] = []
        self.pending_waits = 0
        self._stopped = asyncio.Event()

    async def wait_stopped(self) -> None:
        await self._stopped.wait()

    async def stop(self, reason: str) -> None:
        self.stop_calls.append(reason)

    async def wait_for_pending(self) -> None:
        self.pending_waits += 1


class HangingListener:
    def __init__(self) -> None:
        self.cancelled = False

    async def wait_for_pending(self) -> None:
        try:
            await asyncio.Event().wait()
        finally:
            self.cancelled = True


def _target(platform_shop_id: str = "9121478993551097445"):
    return SimpleNamespace(platform_shop_id=platform_shop_id)


def test_sample_page_match_requires_exact_path_and_shop() -> None:
    assert _sample_page_matches(
        "https://affiliate.tiktokshopglobalselling.com"
        f"{SAMPLE_PAGE_PATH}?shop_region=US&shop_id=9121478993551097445",
        "9121478993551097445",
    )
    assert not _sample_page_matches(
        "https://affiliate.tiktokshopglobalselling.com"
        f"{SAMPLE_PAGE_PATH}?shop_region=US&shop_id=other",
        "9121478993551097445",
    )


def test_cross_border_launcher_paginates_review_without_full_mode() -> None:
    source = Path("scripts/start-hubstudio-sample-watches.ps1").read_text(
        encoding="utf-8"
    )

    assert "scripts.run_hubstudio_raw_sample_watch" in source
    assert "--full" not in source
    assert "--defer-feishu" not in source
    assert "[double]$IntervalSeconds = 60" in source


def test_sample_page_match_accepts_local_affiliate_host() -> None:
    assert _sample_page_matches(
        "https://affiliate-us.tiktok.com"
        f"{SAMPLE_PAGE_PATH}?shop_region=US&shop_id=9136806951995371293",
        "9136806951995371293",
    )


def test_load_first_page_reuses_exact_shop_page() -> None:
    page = FakePage(
        "https://affiliate.tiktokshopglobalselling.com"
        f"{SAMPLE_PAGE_PATH}?shop_region=US&shop_id=9121478993551097445"
    )
    context = FakeContext([page])

    selected = asyncio.run(_load_first_page([context], _target()))

    assert selected is page
    assert page.reload_count == 1
    assert page.goto_urls == []
    assert page.review_locator.clicks == 0
    assert page.sort_locator.clicks == 1
    assert page.date_locator.clicks == 1


def test_load_first_page_continues_after_matching_page_reload_timeout() -> None:
    page = FakePage(
        "https://affiliate.tiktokshopglobalselling.com"
        f"{SAMPLE_PAGE_PATH}?shop_region=US&shop_id=9121478993551097445"
    )
    page.reload_failures = 1

    selected = asyncio.run(_load_first_page([FakeContext([page])], _target()))

    assert selected is page
    assert page.reload_count == 1
    assert page.review_locator.clicks == 0


def test_load_first_page_creates_page_without_reusing_other_shop() -> None:
    other = FakePage(
        "https://affiliate.tiktokshopglobalselling.com"
        f"{SAMPLE_PAGE_PATH}?shop_region=US&shop_id=other"
    )
    context = FakeContext([other])

    selected = asyncio.run(_load_first_page([context], _target()))

    assert selected is context.created
    assert "shop_id=9121478993551097445" in selected.goto_urls[0]
    assert selected.reload_count == 0
    assert other.goto_urls == []
    assert selected.review_locator.clicks == 0
    assert selected.sort_locator.clicks == 1
    assert selected.date_locator.clicks == 1


def test_load_first_page_does_not_add_tab_when_context_is_full() -> None:
    context = FakeContext([FakePage(f"https://example.com/page/{index}") for index in range(8)])

    with pytest.raises(RuntimeError, match="tab_limit_reached"):
        asyncio.run(_load_first_page([context], _target()))

    assert len(context.pages) == 8


def test_load_first_page_closes_created_page_redirected_to_error_page() -> None:
    context = FakeContext([])
    context.created.redirect_url = (
        "https://affiliate.tiktokshopglobalselling.com/errorpage?"
    )

    with pytest.raises(RuntimeError, match="redirected to an error page"):
        asyncio.run(_load_first_page([context], _target()))

    assert context.created.closed is True


def test_load_first_page_closes_reused_page_redirected_to_error_page() -> None:
    page = FakePage(
        "https://affiliate.tiktokshopglobalselling.com"
        f"{SAMPLE_PAGE_PATH}?shop_region=US&shop_id=9121478993551097445"
    )
    page.redirect_url = "https://affiliate.tiktokshopglobalselling.com/errorpage"

    with pytest.raises(RuntimeError, match="redirected to an error page"):
        asyncio.run(_load_first_page([FakeContext([page])], _target()))

    assert page.closed is True


def test_next_page_clicks_only_an_enabled_next_control() -> None:
    enabled = FakePage("page", next_count=1)
    disabled = FakePage("page", next_count=0)

    assert asyncio.run(next_sample_page(enabled)) is True
    assert enabled.next_locator.clicks == 1
    assert enabled.next_locator.click_kwargs[0]["no_wait_after"] is True
    assert asyncio.run(next_sample_page(disabled)) is False


def test_select_review_status_keeps_selected_exact_tab() -> None:
    page = FakePage("page")

    asyncio.run(_select_review_status(page))

    assert page.review_locator.clicks == 0


def test_select_review_status_clicks_only_when_not_selected() -> None:
    page = FakePage("page")
    page.review_locator = FakeLocator(
        1,
        on_click=lambda: page.review_locator._attributes.update(
            {"aria-selected": "true"}
        ),
    )

    asyncio.run(_select_review_status(page))

    assert page.review_locator.clicks == 1
    assert page.review_locator.click_kwargs[0]["timeout"] == 30_000
    assert page.review_locator.click_kwargs[0]["force"] is True
    assert page.review_locator.click_kwargs[0]["no_wait_after"] is True
    assert page.wait_timeouts == [1_500]


def test_select_review_status_retries_forced_tab_after_timeout() -> None:
    page = FakePage("page")
    page.review_locator = FakeLocator(
        1,
        click_failures=1,
        on_click=lambda: page.review_locator._attributes.update(
            {"aria-selected": "true"}
        ),
    )

    asyncio.run(_select_review_status(page))

    assert page.review_locator.clicks == 2
    assert page.review_locator.click_kwargs[0]["force"] is True
    assert page.review_locator.click_kwargs[-1]["force"] is True
    assert page.review_locator.click_kwargs[-1]["no_wait_after"] is True


def test_select_request_date_sets_latest_sort() -> None:
    page = FakePage("page")

    asyncio.run(_select_request_date(page))

    assert page.sort_locator.clicks == 1
    assert page.date_locator.clicks == 1
    assert page.sort_locator.click_kwargs[0]["no_wait_after"] is True
    assert page.date_locator.click_kwargs[0]["no_wait_after"] is True


def test_capture_timeout_keeps_listener_alive_for_next_cycle() -> None:
    page = FakePage(
        "https://affiliate.tiktokshopglobalselling.com"
        f"{SAMPLE_PAGE_PATH}?shop_region=US&shop_id=9121478993551097445"
    )
    listener = FakeListener()
    cycle = _CycleState(asyncio.Event())

    status = asyncio.run(
        _run_cycle(
            [FakeContext([page])],
            _target(),
            cycle,
            listener,  # type: ignore[arg-type]
            asyncio.Event(),
            0.001,
        )
    )

    assert status == "capture_timeout"
    assert listener.stop_calls == []


def test_processing_timeout_cancels_stuck_capture_task() -> None:
    listener = HangingListener()

    completed = asyncio.run(_wait_for_processing(listener, 0.001))

    assert completed is False
    assert listener.cancelled is True


def test_run_cycle_waits_for_listener_before_clicking_next_page() -> None:
    page = FakePage(
        "https://affiliate.tiktokshopglobalselling.com"
        f"{SAMPLE_PAGE_PATH}?shop_region=US&shop_id=9121478993551097445",
        next_count=1,
    )
    listener = FakeListener()
    cycle = _CycleState(asyncio.Event())

    async def exercise() -> str:
        original_click = page.next_locator.click

        async def publish_last_page(**kwargs) -> None:
            await original_click(**kwargs)
            cycle.ingest_result = SimpleNamespace(status="succeeded")
            cycle.event.set()

        page.next_locator.click = publish_last_page  # type: ignore[method-assign]

        async def publish_first_page() -> None:
            await asyncio.sleep(0)
            cycle.ingest_result = SimpleNamespace(status="running")
            cycle.event.set()

        publisher = asyncio.create_task(publish_first_page())
        status = await _run_cycle(
            [FakeContext([page])],
            _target(),
            cycle,
            listener,  # type: ignore[arg-type]
            asyncio.Event(),
            1,
        )
        await publisher
        return status

    assert asyncio.run(exercise()) == "succeeded"
    assert listener.pending_waits == 1
    assert page.next_locator.clicks == 1


def test_select_request_date_retries_when_option_is_detached() -> None:
    page = FakePage("page")
    page.date_locator = FakeLocator(
        1,
        "Application date",
        click_failures=1,
        on_click=lambda: setattr(page.sort_locator, "_text", "Application date"),
    )

    asyncio.run(_select_request_date(page))

    assert page.sort_locator.clicks == 2
    assert page.date_locator.clicks == 2
    assert page.date_locator.visible_filters == 2


def test_select_request_date_rejects_layout_without_sort_control() -> None:
    page = FakePage("page")
    page.sort_locator = FakeLocator(0)

    with pytest.raises(RuntimeError, match="sample_request_date_sort_unavailable"):
        asyncio.run(_select_request_date(page, attempts=1))

    assert page.sort_locator.clicks == 0
    assert page.date_locator.clicks == 0


def test_profile_details_are_captured_before_feishu_sync() -> None:
    calls = []
    capture = SimpleNamespace(
        target=SimpleNamespace(tenant_id="tenant", shop_id="shop")
    )

    class Targets:
        async def list_targets(self, _capture):
            calls.append("targets")
            return [SimpleNamespace(username="creator")]

    class Profiles:
        async def capture(self, _contexts, targets):
            calls.append("profiles")
            assert [target.username for target in targets] == ["creator"]
            return 1

    class Feishu:
        async def sync(self, *, tenant_id, shop_id):
            calls.append("feishu")
            assert (tenant_id, shop_id) == ("tenant", "shop")
            return SimpleNamespace(updated_count=1)

    result = asyncio.run(
        _capture_profiles_then_sync(
            capture,
            contexts=[SimpleNamespace()],
            profile_target_provider=Targets(),
            profile_collector=Profiles(),
            feishu_sync_service=Feishu(),
        )
    )

    assert calls == ["targets", "profiles", "feishu"]
    assert result.profile_captured == 1
    assert result.profile_error_type is None


def test_profile_capture_failure_does_not_block_base_feishu_sync() -> None:
    calls = []
    capture = SimpleNamespace(
        target=SimpleNamespace(tenant_id="tenant", shop_id="shop")
    )

    class Targets:
        async def list_targets(self, _capture):
            return [SimpleNamespace(username="creator")]

    class Profiles:
        async def capture(self, _contexts, _targets):
            raise TimeoutError("details unavailable")

    class Feishu:
        async def sync(self, *, tenant_id, shop_id):
            calls.append((tenant_id, shop_id))
            return SimpleNamespace(updated_count=1)

    result = asyncio.run(
        _capture_profiles_then_sync(
            capture,
            contexts=[SimpleNamespace()],
            profile_target_provider=Targets(),
            profile_collector=Profiles(),
            feishu_sync_service=Feishu(),
        )
    )

    assert calls == [("tenant", "shop")]
    assert result.profile_captured == 0
    assert result.profile_error_type == "TimeoutError"


def test_hubstudio_capture_uses_post_source_pipeline_when_available() -> None:
    calls = []
    source_result = SimpleNamespace(application_ids=("application-1",))
    capture = SimpleNamespace(
        target=SimpleNamespace(tenant_id="tenant", shop_id="shop")
    )

    class Targets:
        async def list_targets(self, _capture):
            calls.append("targets")
            return []

    class Profiles:
        async def capture(self, _contexts, _targets):
            calls.append("profiles")
            return 0

    class DirectFeishu:
        async def sync(self, **_kwargs):
            raise AssertionError("post-source pipeline must own Feishu sync")

    class PostSource:
        async def complete_after_source(self, **kwargs):
            calls.append("pipeline-start")
            await kwargs.pop("profile_capture")()
            calls.append("pipeline-end")
            calls.append(kwargs)
            return SimpleNamespace(feishu_result=SimpleNamespace(updated_count=2))

    result = asyncio.run(
        _capture_profiles_then_sync(
            capture,
            contexts=[SimpleNamespace()],
            profile_target_provider=Targets(),
            profile_collector=Profiles(),
            feishu_sync_service=DirectFeishu(),
            post_source_service=PostSource(),
            source_result=source_result,
        )
    )

    assert result.sync_result.updated_count == 2
    assert calls == [
        "pipeline-start",
        "targets",
        "profiles",
        "pipeline-end",
        {
            "tenant_id": "tenant",
            "shop_id": "shop",
            "source_type": "hubstudio_cdp",
            "source_results": (source_result,),
        },
    ]


def test_hubstudio_capture_holds_shared_shop_lock() -> None:
    calls = []
    capture = SimpleNamespace(
        target=SimpleNamespace(tenant_id="tenant", shop_id="shop")
    )

    class ShopLock:
        @asynccontextmanager
        async def acquire(self, tenant_id, shop_id):
            assert (tenant_id, shop_id) == ("tenant", "shop")
            calls.append("lock-acquired")
            yield True
            calls.append("lock-released")

    class PostSource:
        async def complete_after_source(self, **_kwargs):
            calls.append("pipeline")
            return SimpleNamespace(feishu_result=SimpleNamespace(updated_count=1))

    result = asyncio.run(
        _capture_profiles_then_sync(
            capture,
            contexts=[],
            profile_target_provider=object(),
            profile_collector=object(),
            feishu_sync_service=object(),
            post_source_service=PostSource(),
            shop_sync_lock=ShopLock(),
        )
    )

    assert calls == ["lock-acquired", "pipeline", "lock-released"]
    assert result.sync_result.updated_count == 1


def test_hubstudio_capture_defers_pipeline_when_shop_lock_is_busy(monkeypatch) -> None:
    calls = []
    capture = SimpleNamespace(
        target=SimpleNamespace(tenant_id="tenant", shop_id="shop")
    )

    class ShopLock:
        @asynccontextmanager
        async def acquire(self, _tenant_id, _shop_id):
            yield False

    class PostSource:
        async def complete_after_source(self, **_kwargs):
            calls.append("pipeline")

    events = []
    monkeypatch.setattr(
        "backend.app.services.hubstudio_sample_watch.capture_log",
        lambda event, **values: events.append((event, values)),
    )

    result = asyncio.run(
        _capture_profiles_then_sync(
            capture,
            contexts=[],
            profile_target_provider=object(),
            profile_collector=object(),
            feishu_sync_service=object(),
            post_source_service=PostSource(),
            shop_sync_lock=ShopLock(),
        )
    )

    assert calls == []
    assert result.processing_error_type is None
    assert events == [
        (
            "hubstudio_sample_sync_deferred",
            {"tenant_id": "tenant", "shop_id": "shop", "reason": "shop_sync_busy"},
        )
    ]


def test_hubstudio_sample_watcher_wires_shared_shop_lock() -> None:
    source = Path("scripts/run_hubstudio_sample_watch.py").read_text(encoding="utf-8")

    assert "SampleShopSyncLock(database)" in source
    assert "shop_sync_lock=" in source


def test_hubstudio_sample_watcher_reads_every_review_page_by_default() -> None:
    source = Path("scripts/run_hubstudio_sample_watch.py").read_text(encoding="utf-8")

    assert "latest_window=False" in source


def test_post_source_failure_is_reported_without_stopping_capture() -> None:
    capture = SimpleNamespace(
        target=SimpleNamespace(tenant_id="tenant", shop_id="shop")
    )

    class Targets:
        async def list_targets(self, _capture):
            return []

    class Profiles:
        async def capture(self, _contexts, _targets):
            return 0

    class DirectFeishu:
        async def sync(self, **_kwargs):
            raise AssertionError("post-source pipeline must own Feishu sync")

    class PostSource:
        async def complete_after_source(self, **_kwargs):
            raise TimeoutError("temporary downstream failure")

    result = asyncio.run(
        _capture_profiles_then_sync(
            capture,
            contexts=[SimpleNamespace()],
            profile_target_provider=Targets(),
            profile_collector=Profiles(),
            feishu_sync_service=DirectFeishu(),
            post_source_service=PostSource(),
            source_result=SimpleNamespace(application_ids=()),
        )
    )

    assert result.processing_error_type == "TimeoutError"
