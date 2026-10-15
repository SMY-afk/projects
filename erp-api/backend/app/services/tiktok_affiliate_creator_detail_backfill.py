from __future__ import annotations

import asyncio
from collections.abc import Iterable
from datetime import date, timedelta
from time import monotonic
from typing import Protocol
from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import UUID

from playwright.async_api import BrowserContext, Page

from backend.app.services.capture_logging import capture_log as _log
from backend.app.services.tiktok_affiliate_analytics_page_control import (
    is_affiliate_host,
    page_security_failure,
)
from backend.app.services.tiktok_affiliate_creator_concurrency import (
    run_creator_workers,
)
from backend.app.services.tiktok_affiliate_creator_identity_collector import (
    DATE_RANGE,
    HOST,
    PAGE_PATH,
    CreatorDetailBackfillError,
    collect_creator_identities,
    page_platform_shop_id,
    page_window,
)
from backend.app.services.tiktok_affiliate_intent_page import _select_creator_date
from erp_api.services.affiliate_center_metric_dtos import AffiliateCreatorMetricDTO
from erp_api.services.affiliate_center_read_repository import (
    AffiliateCenterReadRepository,
)
from erp_api.services.affiliate_creator_detail_backfill_repository import (
    AffiliateCreatorDetailBackfillRepository,
    CreatorDetailBackfillTarget,
)
from erp_api.services.creator_sync_state_repository import (
    CreatorSyncCandidate,
    CreatorSyncOutcome,
    CreatorSyncStateRepository,
)


class DetailPageCapture(Protocol):
    async def capture_page(self, page: Page) -> None: ...


class TikTokAffiliateCreatorDetailBackfill:
    def __init__(
        self,
        tenant_id: UUID,
        database,
        capture: DetailPageCapture,
        *,
        max_creators: int = 600,
        max_pages: int = 100,
        max_runtime_seconds: float = 10_800,
        min_request_interval: float = 0.8,
        concurrency: int = 5,
        stale_after_hours: float = 24,
        creator_usernames: frozenset[str] | None = None,
    ) -> None:
        self._tenant_id = tenant_id
        self._read = AffiliateCenterReadRepository(database)
        self._repository = AffiliateCreatorDetailBackfillRepository(database)
        self._sync_states = CreatorSyncStateRepository(database)
        self._capture = capture
        self._max_creators = max_creators
        self._max_pages = max_pages
        self._max_runtime = max_runtime_seconds
        self._request_interval = min_request_interval
        self._concurrency = concurrency
        self._stale_after = timedelta(hours=stale_after_hours)
        self._creator_usernames = creator_usernames or frozenset()

    async def run(
        self, contexts: Iterable[BrowserContext], stopped: asyncio.Event
    ) -> None:
        started_at = monotonic()
        candidates: list[tuple[Page, CreatorDetailBackfillTarget]] = []
        for context in contexts:
            for page in tuple(context.pages):
                target = await self._target_for_page(page)
                if target is not None:
                    candidates.append((page, target))
        candidates.sort(key=lambda item: item[1].query.window_start, reverse=True)
        _log(
            "affiliate_creator_detail_backfill_started",
            tenant_id=self._tenant_id,
            records_unique=len(candidates),
        )
        for page, target in candidates:
            if stopped.is_set() or monotonic() - started_at > self._max_runtime:
                return
            try:
                records = await collect_creator_identities(
                    page,
                    target,
                    self._tenant_id,
                    max_pages=self._max_pages,
                    request_interval=self._request_interval,
                )
                await self._crawl_details(page, target, records, stopped, started_at)
            except asyncio.CancelledError:
                raise
            except CreatorDetailBackfillError:
                _log(
                    "affiliate_creator_detail_backfill_failed",
                    tenant_id=self._tenant_id,
                    shop_id=target.query.shop_id,
                )
            except Exception as error:  # noqa: BLE001 -- browser batch boundary
                _log(
                    "affiliate_creator_detail_backfill_failed",
                    tenant_id=self._tenant_id,
                    shop_id=target.query.shop_id,
                    error_type=type(error).__name__,
                )

    async def _target_for_page(self, page: Page) -> CreatorDetailBackfillTarget | None:
        split = urlsplit(page.url)
        if (
            not is_affiliate_host(split.hostname)
            or split.path != PAGE_PATH
            or "creator_id" in parse_qs(split.query)
        ):
            return None
        external_shop_id = page_platform_shop_id(page.url)
        if not external_shop_id:
            return None
        shop = await self._read.get_shop_context_by_platform_id(
            self._tenant_id, external_shop_id
        )
        shop_id = shop.get("shopId") if shop else None
        if not isinstance(shop_id, UUID):
            return None
        window = await page_window(page)
        if window is None:
            return None
        return await self._repository.target_for_window(
            self._tenant_id,
            shop_id,
            external_shop_id,
            window[0],
            window[1],
        )

    async def _crawl_details(
        self,
        list_page: Page,
        target: CreatorDetailBackfillTarget,
        records: list[AffiliateCreatorMetricDTO],
        stopped: asyncio.Event,
        started_at: float,
    ) -> None:
        split = urlsplit(list_page.url)
        region = parse_qs(split.query).get("shop_region", ["US"])[0]
        candidates = await self._sync_states.prepare_candidates(
            self._tenant_id,
            target.query.shop_id,
            records,
            stale_after=self._stale_after,
        )
        if self._creator_usernames:
            candidates = [
                candidate
                for candidate in candidates
                if candidate.record.username_normalized in self._creator_usernames
            ]
        candidates = candidates[: self._max_creators]
        _log(
            "affiliate_creator_incremental_selected",
            tenant_id=self._tenant_id,
            shop_id=target.query.shop_id,
            records_unique=len(candidates),
            expected_total=len(records),
        )

        detail_page = list_page
        list_url = list_page.url

        async def process(candidate: CreatorSyncCandidate) -> CreatorSyncCandidate:
            if stopped.is_set() or monotonic() - started_at > self._max_runtime:
                raise CreatorDetailBackfillError("runtime_exceeded")
            if await self._repository.is_complete(
                self._tenant_id, target, (candidate.affiliate_creator_id,)
            ):
                return candidate
            try:
                response = await detail_page.goto(
                    _detail_url(
                        target,
                        region,
                        candidate.platform_creator_id,
                        split.hostname or HOST,
                    ),
                    wait_until="domcontentloaded",
                )
                if response is not None and response.status == 429:
                    raise CreatorDetailBackfillError("http_429")
                await _set_window(detail_page, target)
                await asyncio.wait_for(
                    self._capture.capture_page(detail_page), timeout=120
                )
                failure = await page_security_failure(detail_page)
                if failure is not None:
                    raise CreatorDetailBackfillError(failure[1])
                return candidate
            except TimeoutError as error:
                raise CreatorDetailBackfillError("detail_timeout") from error

        try:
            results = await run_creator_workers(
                candidates,
                process,
                concurrency=1,
                backoff_base_seconds=max(self._request_interval, 0.1),
            )
        finally:
            try:
                await detail_page.goto(list_url, wait_until="domcontentloaded")
            except Exception:  # noqa: BLE001 -- keep cleanup from hiding batch outcome
                _log(
                    "affiliate_creator_detail_list_restore_failed",
                    tenant_id=self._tenant_id,
                    shop_id=target.query.shop_id,
                )
        outcomes = [
            CreatorSyncOutcome(candidate, result is not None)
            for candidate, result in zip(candidates, results, strict=True)
        ]
        await self._sync_states.mark_outcomes(
            self._tenant_id,
            target.query.shop_id,
            outcomes,
        )
        completed = sum(outcome.succeeded for outcome in outcomes)
        _log(
            "affiliate_creator_detail_backfill_completed",
            tenant_id=self._tenant_id,
            shop_id=target.query.shop_id,
            records_unique=completed,
            expected_total=len(records),
        )


async def _set_window(page: Page, target: CreatorDetailBackfillTarget) -> None:
    date_range = page.locator(DATE_RANGE)
    inputs = date_range.locator("input")
    await inputs.nth(1).wait_for(state="visible", timeout=30_000)
    current = [await inputs.nth(index).input_value() for index in range(2)]
    requested = [
        target.query.window_start.isoformat(),
        target.query.window_end.isoformat(),
    ]
    if current == requested:
        return
    if bool(current[0]) != bool(current[1]):
        await date_range.click()
        await _select_creator_date(page, date.fromisoformat(current[0] or current[1]))
    await date_range.click()
    await _select_creator_date(page, target.query.window_start)
    await _select_creator_date(page, target.query.window_end)
    selected = [await inputs.nth(index).input_value() for index in range(2)]
    if selected != requested:
        raise CreatorDetailBackfillError("detail_window_not_settable")


def _detail_url(
    target: CreatorDetailBackfillTarget,
    region: str,
    platform_creator_id: str,
    host: str = HOST,
) -> str:
    query = urlencode(
        {
            "creator_id": platform_creator_id,
            "shop_region": region,
            "shop_id": target.platform_shop_id,
        }
    )
    return f"https://{host}{PAGE_PATH}?{query}"
