from __future__ import annotations

import asyncio
from collections.abc import Mapping
from time import monotonic
from urllib.parse import urlsplit
from uuid import UUID

from playwright.async_api import Page, Response

from backend.app.services.capture_logging import capture_log as _log
from backend.app.services.tiktok_affiliate_analytics_page_control import (
    is_affiliate_host,
)
from backend.app.services.tiktok_affiliate_contract import platform_shop_id
from backend.app.services.tiktok_affiliate_creator_detail_page import (
    advance_detail_page,
    approved_filters,
    drive_detail_tabs,
    http_failure,
    response_page,
    select_first_detail_page,
)
from backend.app.services.tiktok_affiliate_creator_detail_page import (
    request_id as response_request_id,
)
from backend.app.services.tiktok_affiliate_creator_detail_types import (
    ActiveCreatorDetail,
    CreatorDetailCaptureError,
    track_creator_detail_task,
)
from erp_api.infrastructure.database import Database
from erp_api.services.affiliate_center_read_repository import (
    AffiliateCenterReadRepository,
)
from erp_api.services.affiliate_creator_detail_currency import (
    creator_detail_currency,
)
from erp_api.services.affiliate_creator_detail_parser import (
    CreatorDetailPage,
    discriminate_creator_detail,
    parse_creator_detail_page,
)
from erp_api.services.affiliate_creator_detail_repository import (
    AffiliateCreatorDetailRepository,
)
from erp_api.services.affiliate_creator_detail_video_adapter import (
    creator_detail_video_page,
)
from erp_api.services.affiliate_video_cover_storage import (
    configured_video_cover_writer,
)
from erp_api.services.affiliate_video_persistence import AffiliateVideoPersistence
from erp_api.services.analytics_repository import AnalyticsRepository
from erp_api.services.video_performance_repository import VideoPerformanceRepository

_PAGE_PATH = "/data/creator-analysis"
_PATH_PREFIX = "/api/v2/insights/affiliate/seller/creator_analytics/creator/"


class TikTokAffiliateCreatorDetailCapture:
    def __init__(
        self,
        tenant_id: UUID,
        database: Database,
        mutation_lock: asyncio.Lock,
        *,
        max_pages: int = 100,
        max_runtime_seconds: float = 600,
        min_request_interval: float = 0.8,
    ) -> None:
        self._tenant_id = tenant_id
        self._read = AffiliateCenterReadRepository(database)
        self._repository = AffiliateCreatorDetailRepository(database)
        self._videos = AffiliateVideoPersistence(
            AnalyticsRepository(database),
            VideoPerformanceRepository(database),
            cover_storage=configured_video_cover_writer(),
        )
        self._lock = mutation_lock
        self._max_pages = max_pages
        self._max_runtime = max_runtime_seconds
        self._request_interval = min_request_interval
        self._active: dict[tuple[int, str], ActiveCreatorDetail] = {}
        self._events: dict[tuple[int, str], asyncio.Event] = {}
        self._shop_currencies: dict[UUID, str] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self._page_failures: dict[int, str] = {}

    def schedule_response(self, response: Response) -> None:
        task = asyncio.create_task(self.handle_response(response))
        track_creator_detail_task(self._tasks, task)

    async def handle_response(self, response: Response) -> None:
        split = urlsplit(response.url)
        if (
            not is_affiliate_host(split.hostname)
            or response.request.method.upper() != "POST"
            or not split.path.startswith(_PATH_PREFIX)
        ):
            return
        page = response_page(response)
        if page is None or urlsplit(page.url).path != _PAGE_PATH:
            return
        try:
            body = response.request.post_data_json
            if not isinstance(body, Mapping):
                raise TypeError("Creator detail request body is unavailable.")
            kind = discriminate_creator_detail(split.path, body)
            if kind is None:
                return
            if response.status in {401, 403, 429}:
                await self._fail(page, kind, http_failure(response.status))
                return
            if response.status != 200:
                await self._fail(page, kind, "http_status")
                return
            content_type = await response.header_value("content-type")
            if not (content_type or "").casefold().startswith("application/json"):
                await self._fail(page, kind, "payload_content_type_changed")
                return
            request_id = await response_request_id(response)
            if not request_id:
                raise ValueError("Creator detail request ID is missing.")
            payload = await response.json()
            if not isinstance(payload, Mapping):
                raise TypeError("Creator detail payload must be an object.")
            await self._persist(page, kind, payload, body, request_id, response.url)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 -- browser response boundary
            kind = locals().get("kind")
            if isinstance(kind, str):
                await self._fail(page, kind, "payload_structure_changed")
            _log("affiliate_creator_detail_response_failed", tenant_id=self._tenant_id)

    async def _persist(
        self,
        browser_page: Page,
        kind: str,
        payload: Mapping[str, object],
        body: Mapping[str, object],
        request_id: str,
        response_url: str,
    ) -> None:
        external_shop_id = platform_shop_id(response_url)
        if not external_shop_id:
            raise ValueError("Creator detail shop identifier is missing.")
        shop = await self._read.get_shop_context_by_platform_id(
            self._tenant_id, external_shop_id
        )
        if shop is None:
            raise ValueError("Creator detail shop is not active in ERP.")
        shop_id = shop.get("shopId")
        timezone = shop.get("shopTimezone")
        currency = creator_detail_currency(
            payload, shop.get("currency") or self._shop_currencies.get(shop_id)
        )
        if not isinstance(shop_id, UUID) or not isinstance(timezone, str):
            raise TypeError("Creator detail shop context is incomplete.")
        if not isinstance(currency, str):
            raise TypeError("Creator detail shop currency is unavailable.")
        self._shop_currencies[shop_id] = currency
        parsed = parse_creator_detail_page(
            kind, payload, body, currency, shop_timezone=timezone
        )
        filters = approved_filters(body)
        key = (id(browser_page), kind)
        query_key = (
            parsed.platform_creator_id,
            parsed.window_start_utc,
            parsed.window_end_utc,
            currency,
            tuple(sorted(filters.items())),
        )
        if self._active.get(key) is None and parsed.page_number != 1:
            if await select_first_detail_page(browser_page):
                return
            raise ValueError("Creator detail capture did not start from page one.")
        async with self._lock:
            active = self._active.get(key)
            if active is not None and active.query_key != query_key:
                await self._repository.finalize(
                    self._tenant_id,
                    active.report_id,
                    terminal=False,
                    failure_reason="query_changed",
                )
                active = None
            if active is None:
                report_id, run_id = await self._repository.start_report(
                    self._tenant_id,
                    shop_id,
                    parsed,
                    shop_timezone=timezone,
                    currency=currency,
                    filters=filters,
                )
                active = ActiveCreatorDetail(report_id, run_id, browser_page, query_key)
                self._active[key] = active
            if parsed.page_number in active.seen_pages:
                return
            if len(active.seen_pages) >= self._max_pages:
                await self._finish(key, active, False, "max_pages_exceeded")
                return
            if monotonic() - active.started_at > self._max_runtime:
                await self._finish(key, active, False, "runtime_exceeded")
                return
            if kind == "video":
                video_page = creator_detail_video_page(
                    parsed,
                    shop_id=shop_id,
                    shop_timezone=timezone,
                    currency=currency,
                    request_id=request_id,
                    raw_payload=dict(payload),
                )
                await self._videos.persist_page(
                    self._tenant_id, active.run_id, video_page
                )
            await self._repository.persist_page(
                self._tenant_id,
                active.report_id,
                parsed,
                request_id=request_id,
                raw_payload=dict(payload),
            )
            active.seen_pages.add(parsed.page_number)
            active.empty_pages = active.empty_pages + 1 if not parsed.records else 0
            _log(
                "affiliate_creator_detail_page_persisted",
                tenant_id=self._tenant_id,
                shop_id=shop_id,
                run_id=active.run_id,
                request_id=request_id,
                records_received=len(parsed.records),
            )
            if not parsed.has_more:
                await self._finish(key, active, True, None)
                return
            if active.empty_pages >= 2:
                await self._finish(key, active, False, "consecutive_empty_pages")
                return
        await asyncio.sleep(self._request_interval)
        await self._advance(browser_page, key, active, parsed)

    async def _advance(
        self,
        page: Page,
        key: tuple[int, str],
        active: ActiveCreatorDetail,
        parsed: CreatorDetailPage,
    ) -> None:
        advanced, reason = await advance_detail_page(page, parsed.page_number)
        if not advanced:
            await self._finish(key, active, False, reason or "cursor_interrupted")

    async def _finish(self, key, active, terminal, reason) -> None:
        await self._repository.finalize(
            self._tenant_id,
            active.report_id,
            terminal=terminal,
            failure_reason=reason,
        )
        self._events.setdefault(key, asyncio.Event()).set()
        self._active.pop(key, None)

    async def _fail(self, page: Page, kind: str, reason: str) -> None:
        key = (id(page), kind)
        self._page_failures[id(page)] = reason
        active = self._active.get(key)
        if active is not None:
            async with self._lock:
                await self._finish(key, active, False, reason)
        else:
            self._events.setdefault(key, asyncio.Event()).set()

    def start_open_pages(self, pages: list[Page]) -> None:
        for page in pages:
            if urlsplit(page.url).path == _PAGE_PATH and "creator_id=" in page.url:
                task = asyncio.create_task(self.capture_page(page))
                track_creator_detail_task(self._tasks, task)

    async def capture_page(self, page: Page) -> None:
        self._page_failures.pop(id(page), None)
        await (
            page.locator('[role="tab"]')
            .nth(3)
            .wait_for(state="visible", timeout=30_000)
        )
        await drive_detail_tabs(page, self._events, self._max_runtime, self._fail)
        failure = self._page_failures.pop(id(page), None)
        if failure is not None:
            raise CreatorDetailCaptureError(failure)

    async def wait_for_pending(self) -> None:
        if self._tasks:
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)

    async def stop(self) -> None:
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
