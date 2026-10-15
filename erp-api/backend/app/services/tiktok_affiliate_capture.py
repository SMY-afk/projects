from __future__ import annotations

import asyncio
from urllib.parse import urlsplit
from uuid import UUID

from playwright.async_api import Response

from app.parsers.affiliate_order_parser import (
    AffiliateOrderParseError,
    parse_affiliate_order_items,
)
from app.parsers.scraped_data_parser import parse_scraped_data_response
from backend.app.services.capture_logging import capture_log as _log
from backend.app.services.capture_logging import safe_error as _safe_error
from backend.app.services.tiktok_affiliate_contract import (
    TARGET_METHOD,
    TARGET_PATH,
    affiliate_pagination,
    is_affiliate_order_payload,
    platform_shop_id,
)
from backend.app.services.tiktok_affiliate_listener import run_listener
from erp_api.infrastructure.database import Database
from erp_api.services.affiliate_sync_repository import AffiliateSyncRepository
from erp_api.services.scraped_data_repository import ScrapedDataRepository

__all__ = ["run_capture_session", "run_listener"]


class TikTokAffiliateOrderSynchronizer:
    def __init__(
        self,
        raw_repository: ScrapedDataRepository,
        sync_repository: AffiliateSyncRepository,
        tenant_id: UUID,
        mutation_lock: asyncio.Lock | None = None,
    ) -> None:
        self._raw_repository = raw_repository
        self._sync_repository = sync_repository
        self._tenant_id = tenant_id
        self._tasks: set[asyncio.Task[None]] = set()
        self._upsert_lock = mutation_lock or asyncio.Lock()
        self._shop_ids: dict[str, UUID] = {}

    def schedule_response(self, response: Response) -> None:
        task = asyncio.create_task(self.handle_response(response))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def handle_response(self, response: Response) -> None:
        path = urlsplit(response.url).path
        method = response.request.method.upper()
        if path != TARGET_PATH or method != TARGET_METHOD:
            return
        external_shop_id = platform_shop_id(response.url)
        try:
            shop_id = await self._resolve_shop_id(external_shop_id)
        except Exception as error:  # noqa: BLE001 -- capture boundary records failure
            _log(
                "affiliate_sync_failed",
                method=method,
                path=path,
                error_type=type(error).__name__,
                reason="shop_resolution_failed",
            )
            return
        if shop_id is None:
            _log(
                "affiliate_sync_rejected",
                method=method,
                path=path,
                reason="shop_not_found",
            )
            return
        if response.status != 200:
            await self._mark_failed(shop_id, f"HTTP {response.status}")
            _log(
                "affiliate_sync_failed",
                method=method,
                path=path,
                shop_id=shop_id,
                error_type="HttpStatusError",
                status=response.status,
            )
            return
        try:
            payload = await response.json()
        except Exception as error:  # noqa: BLE001 -- response boundary records failure
            await self._mark_failed(shop_id, "Response body is not valid JSON")
            _log(
                "affiliate_sync_failed",
                method=method,
                path=path,
                shop_id=shop_id,
                error_type=type(error).__name__,
            )
            return

        try:
            if not is_affiliate_order_payload(payload):
                raise AffiliateOrderParseError(
                    "Response does not contain data.sku_order_list"
                )
            raw_records = parse_scraped_data_response(payload)
            order_records = parse_affiliate_order_items(payload)
            next_cursor, has_more = affiliate_pagination(payload)
            async with self._upsert_lock:
                raw_result = await self._raw_repository.bulk_upsert(
                    self._tenant_id,
                    raw_records,
                )
                sync_result = await self._sync_repository.bulk_upsert(
                    self._tenant_id,
                    shop_id,
                    order_records,
                    next_cursor=next_cursor,
                    has_more=has_more,
                )
        except Exception as error:  # noqa: BLE001 -- capture boundary records failure
            await self._mark_failed(shop_id, _safe_error(error))
            event = (
                "affiliate_sync_rejected"
                if isinstance(error, AffiliateOrderParseError)
                else "affiliate_sync_failed"
            )
            _log(
                event,
                method=method,
                path=path,
                shop_id=shop_id,
                error_type=type(error).__name__,
                error=_safe_error(error),
            )
            return

        _log(
            "affiliate_orders_synced",
            method=method,
            path=path,
            shop_id=shop_id,
            received=sync_result.received_count,
            unique=sync_result.unique_count,
            raw_upserted=raw_result.upserted_count,
            orders_upserted=sync_result.upserted_count,
            evidence_upserted=sync_result.evidence_count,
            attributions_recalculated=sync_result.attribution_count,
            unmatched_orders=sync_result.unmatched_count,
            has_more=has_more,
            next_cursor_present=next_cursor is not None,
        )

    async def _resolve_shop_id(self, platform_shop_id: str | None) -> UUID | None:
        if platform_shop_id is None:
            return None
        cached = self._shop_ids.get(platform_shop_id)
        if cached is not None:
            return cached
        shop_id = await self._sync_repository.resolve_shop_id(
            self._tenant_id,
            platform_shop_id,
        )
        if shop_id is not None:
            self._shop_ids[platform_shop_id] = shop_id
        return shop_id

    async def _mark_failed(self, shop_id: UUID, error: str) -> None:
        try:
            await self._sync_repository.mark_failed(
                self._tenant_id,
                shop_id,
                error,
            )
        except Exception as state_error:  # noqa: BLE001 -- preserve primary failure
            _log(
                "affiliate_sync_state_failed",
                shop_id=shop_id,
                error_type=type(state_error).__name__,
            )

    async def wait_for_pending(self) -> None:
        if self._tasks:
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)


async def run_capture_session(
    cdp_url: str,
    tenant_id: UUID,
    shop_id: UUID,
    database: Database,
    *,
    health_repository=None,
) -> bool:
    from backend.app.services.tiktok_affiliate_capture_session import (
        run_capture_session as run_intent_capture_session,
    )

    return await run_intent_capture_session(
        cdp_url,
        tenant_id,
        shop_id,
        database,
        health_repository=health_repository,
    )


def main() -> None:
    from backend.app.services.tiktok_affiliate_listener_cli import main as cli_main

    cli_main()


if __name__ == "__main__":
    main()
