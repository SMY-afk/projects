from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping

from playwright.async_api import Page

from backend.app.services import tiktok_affiliate_analytics_auto_start as auto_start
from backend.app.services import tiktok_affiliate_analytics_run_state as run_state
from backend.app.services import tiktok_affiliate_video_terminal as video_terminal
from backend.app.services.tiktok_affiliate_analytics_context import (
    AffiliateAnalyticsPagePersister,
    AffiliateAnalyticsResponseContext,
    AffiliateAnalyticsTerminalHandler,
)
from backend.app.services.tiktok_affiliate_analytics_page_control import (
    RESOURCE_PAGE,
    capture_log,
    matches_observation,
    matches_page,
    page_security_failure,
    safe_request_template,
)
from backend.app.services.tiktok_affiliate_pager_logging import (
    log_terminal,
    persistence_failure_event,
)
from backend.app.services.tiktok_affiliate_pager_page_state import PageState
from backend.app.services.tiktok_affiliate_paging_driver import AffiliatePagingDriver


class TikTokAffiliateAnalyticsPager:
    def __init__(
        self,
        mutation_lock: asyncio.Lock,
        *,
        guard_config: run_state.CaptureGuardConfig | None = None,
        settle_delay_seconds: float = 0.5,
        watchdog_interval_seconds: float = 0.5,
        auto_started_resources: set[str] | None = None,
        page_persister: AffiliateAnalyticsPagePersister | None = None,
        terminal_handler: AffiliateAnalyticsTerminalHandler | None = None,
        page_requester: Callable[[int], Awaitable[None]] | None = None,
        page_number_provider: Callable[[], int] | None = None,
    ) -> None:
        self._mutation_lock = mutation_lock
        self._settle_delay_seconds = settle_delay_seconds
        self._watchdog_interval_seconds = watchdog_interval_seconds
        self._guard = run_state.AffiliateAnalyticsRunGuard(guard_config)
        self._request_templates: dict[str, dict[str, str]] = {}
        self._states: dict[str, PageState] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self._watchdogs: dict[str, asyncio.Task[None]] = {}
        self._auto_started_resources = (
            auto_started_resources if auto_started_resources is not None else set()
        )
        self._page_persister = page_persister
        self._terminal_handler = terminal_handler
        self._paging = AffiliatePagingDriver(page_requester, page_number_provider)
        self._stopped = False

    @property
    def request_templates(self) -> dict[str, dict[str, str]]:
        return {key: dict(value) for key, value in self._request_templates.items()}

    @property
    def resource_states(self) -> dict[str, dict[str, object]]:
        return self._guard.snapshots()

    @property
    def auto_started_resources(self) -> set[str]:
        return set(self._auto_started_resources)

    async def start_open_pages_once(self, pages: list[Page]) -> None:
        await auto_start.auto_start_open_pages_once(
            pages,
            mutation_lock=self._mutation_lock,
            started_resources=self._auto_started_resources,
            failure_handler=self.handle_failure,
        )

    async def handle_payload(
        self,
        page: Page,
        resource: str,
        payload: Mapping[str, object],
        observation: dict[str, object],
        response_context: AffiliateAnalyticsResponseContext | None = None,
    ) -> None:
        if self._stopped or self._guard.is_terminal(resource):
            return
        if not self._mutation_lock.locked():
            raise RuntimeError("Pager payload handoff requires the shared lock.")
        page_contract = RESOURCE_PAGE.get(resource)
        if page_contract is None or not matches_page(page, page_contract[0]):
            return
        if not matches_observation(resource, observation):
            return

        self._auto_started_resources.add(resource)

        self._request_templates.setdefault(
            resource,
            safe_request_template(resource, observation, page_contract[0]),
        )
        state = self._states.setdefault(
            resource,
            PageState(page=page, resource=resource, selector=page_contract[1]),
        )
        if state.page is not page:
            return
        if state.active_task is not None and not state.active_task.done():
            return
        task = asyncio.create_task(
            self._advance_after_capture(state, payload, observation, response_context)
        )
        state.active_task = task
        self._tasks.add(task)
        task.add_done_callback(lambda completed: self._task_done(state, completed))

    async def handle_failure(
        self,
        _page: Page | None,
        resource: str,
        status: str,
        category: str,
    ) -> None:
        if not self._mutation_lock.locked():
            raise RuntimeError("Pager failure handoff requires the shared lock.")
        self._guard.fail(resource, status=status, category=category)
        log_terminal(self._guard, resource, "affiliate_analytics_resource_failed")
        await self._finalize_resource(resource)

    async def _advance_after_capture(
        self,
        state: PageState,
        payload: Mapping[str, object],
        observation: Mapping[str, object],
        response_context: AffiliateAnalyticsResponseContext | None,
    ) -> None:
        if self._settle_delay_seconds:
            await asyncio.sleep(self._settle_delay_seconds)
        async with state.page_lock:
            if self._stopped or not matches_page(
                state.page, RESOURCE_PAGE[state.resource][0]
            ):
                return
            security_failure = await page_security_failure(state.page)
            if security_failure is not None:
                await self._fail_guard(state.resource, *security_failure)
                return
            try:
                locator, current_page, next_index = await self._paging.resolve(
                    state.page, state.selector
                )
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001 -- browser boundary
                await self._fail_guard(state.resource, "failed", type(error).__name__)
                return
            if current_page is None:
                await self._fail_guard(
                    state.resource, "partial", "current_page_unknown"
                )
                return
            decision = self._guard.record_page(state.resource, current_page, payload)
            snapshot = self._guard.snapshot(state.resource)
            if not decision.accepted:
                return
            terminal_boundary = (
                self._paging.direct
                and not decision.stop
                and video_terminal.is_direct_video_total_boundary(
                    state.resource, current_page, payload, snapshot, response_context
                )
            )
            if terminal_boundary:
                self._guard.finish_ui_terminal(state.resource)
                snapshot = self._guard.snapshot(state.resource)
            if decision.stop or terminal_boundary:
                next_page = None
            elif self._paging.direct:
                next_page = current_page + 1
            else:
                next_page = None if next_index is None else current_page + 1
            if self._page_persister is not None:
                if response_context is None:
                    await self._fail_guard(state.resource, "failed", "page_failed")
                    return
                try:
                    await self._page_persister(
                        state.resource,
                        payload,
                        observation,
                        response_context,
                        current_page,
                        next_page,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as error:  # noqa: BLE001 -- persistence boundary
                    capture_log(persistence_failure_event(error))
                    await self._fail_guard(state.resource, "failed", "page_failed")
                    return
            capture_log(
                "affiliate_analytics_page_captured",
                pages_fetched=snapshot["pages_fetched"],
                records_received=snapshot["records_received"],
                records_unique=snapshot["records_unique"],
                duplicates=snapshot["duplicates"],
                expected_total=snapshot["expected_total"],
            )
            self._ensure_watchdog(state)
            if decision.stop or terminal_boundary:
                log_terminal(
                    self._guard, state.resource, "affiliate_analytics_resource_stopped"
                )
                await self._finalize_resource(state.resource)
                return
            if not self._paging.direct and next_index is None:
                self._guard.finish_ui_terminal(state.resource)
                log_terminal(
                    self._guard, state.resource, "affiliate_analytics_resource_stopped"
                )
                await self._finalize_resource(state.resource)
                return
            delay = self._guard.remaining_request_delay(state.resource)
            if delay:
                await asyncio.sleep(delay)
            if self._guard.enforce_runtime_limit(state.resource):
                log_terminal(
                    self._guard, state.resource, "affiliate_analytics_resource_stopped"
                )
                await self._finalize_resource(state.resource)
                return
            try:
                await self._paging.advance(locator, next_index, next_page)
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001 -- browser boundary
                await self._fail_guard(state.resource, "failed", type(error).__name__)
                return
            self._guard.mark_request(state.resource)
            capture_log(
                "affiliate_analytics_page_advance_requested",
                pages_fetched=snapshot["pages_fetched"],
            )

    async def _fail_guard(self, resource: str, status: str, category: str) -> None:
        async with self._mutation_lock:
            self._guard.fail(resource, status=status, category=category)
        log_terminal(self._guard, resource, "affiliate_analytics_resource_failed")
        await self._finalize_resource(resource)

    async def _finalize_resource(self, resource: str) -> None:
        if self._terminal_handler is not None:
            await self._terminal_handler(resource, self._guard.snapshot(resource))

    def _ensure_watchdog(self, state: PageState) -> None:
        if not self._watchdog_interval_seconds or state.resource in self._watchdogs:
            return
        task = asyncio.create_task(self._watch_resource(state))
        self._watchdogs[state.resource] = task
        task.add_done_callback(
            lambda completed: self._watchdogs.pop(state.resource, None)
        )

    async def _watch_resource(self, state: PageState) -> None:
        while not self._stopped and not self._guard.is_terminal(state.resource):
            await asyncio.sleep(self._watchdog_interval_seconds)
            if self._stopped or self._guard.is_terminal(state.resource):
                return
            failure = await page_security_failure(state.page)
            if failure is not None:
                await self._fail_guard(state.resource, *failure)
                return
            if self._guard.enforce_runtime_limit(state.resource):
                log_terminal(
                    self._guard, state.resource, "affiliate_analytics_resource_stopped"
                )
                await self._finalize_resource(state.resource)
                return

    def _task_done(self, state: PageState, completed: asyncio.Task[None]) -> None:
        self._tasks.discard(completed)
        if state.active_task is completed:
            state.active_task = None

    async def wait_for_pending(self) -> None:
        if self._tasks:
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)

    async def stop(self) -> None:
        self._stopped = True
        pending = tuple(self._tasks) + tuple(self._watchdogs.values())
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
