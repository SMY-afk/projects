from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

from playwright.async_api import Response

from backend.app.services.capture_logging import capture_log as _log
from backend.app.services.tiktok_affiliate_analytics_page_control import (
    is_affiliate_host,
)
from backend.app.services.tiktok_affiliate_contract import platform_shop_id
from backend.app.services.tiktok_affiliate_creator_detail_page import (
    request_id as response_request_id,
)
from backend.app.services.tiktok_affiliate_creator_detail_page import (
    response_page,
)
from backend.app.services.tiktok_affiliate_creator_detail_types import (
    track_creator_detail_task,
)
from erp_api.infrastructure.database import Database
from erp_api.services.affiliate_center_read_repository import (
    AffiliateCenterReadRepository,
)
from erp_api.services.affiliate_creator_summary_parser import (
    discriminate_creator_summary,
    parse_creator_summary,
)
from erp_api.services.affiliate_creator_summary_repository import (
    AffiliateCreatorSummaryRepository,
)
from erp_api.services.sample_notification_profile_builder import (
    REQUIRED_CREATOR_DETAIL_SOURCES,
)

_PAGE_PATHS = frozenset({"/data/creator-analysis", "/affiliate/creator/detail"})


class TikTokAffiliateCreatorSummaryCapture:
    def __init__(
        self,
        tenant_id: UUID,
        database: Database,
        mutation_lock: asyncio.Lock,
    ) -> None:
        self._tenant_id = tenant_id
        self._read = AffiliateCenterReadRepository(database)
        self._repository = AffiliateCreatorSummaryRepository(database)
        self._lock = mutation_lock
        self._tasks: set[asyncio.Task[None]] = set()
        self._persisted_sources: dict[tuple[UUID, str], set[str]] = {}

    def schedule_response(self, response: Response) -> None:
        task = asyncio.create_task(self.handle_response(response))
        track_creator_detail_task(self._tasks, task)

    async def handle_response(self, response: Response) -> None:
        split = urlsplit(response.url)
        kind = discriminate_creator_summary(split.path)
        if (
            kind is None
            or not is_affiliate_host(split.hostname)
            or response.request.method.upper() != "POST"
            or response.status != 200
        ):
            return
        page = response_page(response)
        if page is None or urlsplit(page.url).path not in _PAGE_PATHS:
            return
        failure_stage = "content_type"
        try:
            content_type = await response.header_value("content-type")
            if not (content_type or "").casefold().startswith("application/json"):
                raise TypeError("Creator summary response must be JSON.")
            failure_stage = "request_body"
            body = response.request.post_data_json
            if not isinstance(body, Mapping):
                raise TypeError("Creator summary request body is unavailable.")
            failure_stage = "response_payload"
            payload = await response.json()
            if not isinstance(payload, Mapping):
                raise TypeError("Creator summary payload must be an object.")
            failure_stage = "request_id"
            request_id = await response_request_id(response)
            if not request_id:
                raise ValueError("Creator summary request ID is missing.")
            failure_stage = "shop_identity"
            external_shop_id = platform_shop_id(response.url) or platform_shop_id(
                page.url
            )
            if not external_shop_id:
                raise ValueError("Creator summary shop identifier is missing.")
            shop = await self._read.get_shop_context_by_platform_id(
                self._tenant_id, external_shop_id
            )
            shop_id = shop.get("shopId") if shop else None
            if not isinstance(shop_id, UUID):
                raise TypeError("Creator summary shop is not active in ERP.")
            failure_stage = "parse_summary"
            summary = parse_creator_summary(
                kind,
                payload,
                body,
                observed_at=datetime.now(UTC),
            )
            if summary.creator_username is None:
                page_username = _page_creator_username(page.url)
                if page_username:
                    summary = replace(summary, creator_username=page_username)
            failure_stage = "persist_summary"
            async with self._lock:
                creator_id = await self._repository.persist(
                    self._tenant_id,
                    shop_id,
                    summary,
                    request_id=request_id,
                    response_path=split.path,
                )
            username = (summary.creator_username or "").strip().lstrip("@").casefold()
            if username:
                key = (shop_id, username)
                self._persisted_sources.setdefault(key, set()).add(
                    summary.resource_kind
                )
            _log(
                "affiliate_creator_summary_persisted",
                tenant_id=self._tenant_id,
                shop_id=shop_id,
                request_id=request_id,
                persisted_count=1,
            )
            del creator_id
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 -- browser response boundary
            _log(
                "affiliate_creator_summary_response_failed",
                tenant_id=self._tenant_id,
                error_type=type(error).__name__,
                error_stage=failure_stage,
            )

    def has_complete_profile(self, shop_id: UUID, username: str) -> bool:
        normalized = username.strip().lstrip("@").casefold()
        sources = self._persisted_sources.get((shop_id, normalized), set())
        return REQUIRED_CREATOR_DETAIL_SOURCES.issubset(sources)

    async def wait_for_pending(self) -> None:
        if self._tasks:
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)

    async def stop(self) -> None:
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


def _page_creator_username(url: str) -> str | None:
    values = parse_qs(urlsplit(url).query).get("cname", [])
    if len(values) != 1:
        return None
    username = values[0].strip().lstrip("@")
    return username if 0 < len(username) <= 255 else None
