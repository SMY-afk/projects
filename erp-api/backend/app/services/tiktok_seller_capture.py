from __future__ import annotations

import asyncio
from collections.abc import Mapping
from urllib.parse import urlsplit
from uuid import UUID

from playwright.async_api import Response, Route

from app.parsers.seller_order_export_parser import parse_seller_order_export
from app.parsers.seller_order_parser import (
    SellerOrderParseError,
    parse_aggregate_response,
    parse_seller_order_response,
)
from app.parsers.seller_video_parser import (
    parse_video_completion_response,
    seller_video_ids,
)
from backend.app.services.capture_logging import capture_log as _log
from backend.app.services.tiktok_affiliate_contract import platform_shop_id
from backend.app.services.tiktok_seller_capture_contract import (
    MAX_EXPORT_BYTES,
    RAW_ONLY_PATHS,
    SELLER_EXPORT_DOWNLOAD_PATH,
    SELLER_EXPORT_FILE_PREFIX,
    SELLER_ORDER_PATH,
    SELLER_VIDEO_COMPLETION_DATA_TYPE,
    SELLER_VIDEO_COMPLETION_PATH,
)
from backend.app.services.tiktok_seller_product_capture import (
    SELLER_PRODUCT_DATA_TYPE,
    SELLER_PRODUCT_LIST_PATH,
    SellerProductCatalogRequester,
)
from erp_api.services.scraped_data_repository import ScrapedDataRepository
from erp_api.services.seller_evidence_sync_repository import (
    SellerEvidenceSyncRepository,
)


class TikTokSellerCenterSynchronizer:
    """Capture allow-listed Seller Center evidence without persisting request secrets."""

    def __init__(
        self,
        raw_repository: ScrapedDataRepository,
        sync_repository: SellerEvidenceSyncRepository,
        tenant_id: UUID,
        mutation_lock: asyncio.Lock | None = None,
        enable_product_fallback: bool = False,
    ) -> None:
        self._raw_repository = raw_repository
        self._sync_repository = sync_repository
        self._tenant_id = tenant_id
        self._tasks: set[asyncio.Task[None]] = set()
        self._lock = mutation_lock or asyncio.Lock()
        self._shop_ids: dict[str, UUID] = {}
        self._export_downloads: dict[tuple[str, str], UUID] = {}
        self._completion_requested_at: dict[str, float] = {}
        self._product_catalog = SellerProductCatalogRequester()
        self._raw_only_paths = RAW_ONLY_PATHS | (
            {SELLER_PRODUCT_LIST_PATH: SELLER_PRODUCT_DATA_TYPE}
            if enable_product_fallback
            else {}
        )

    def schedule_response(self, response: Response) -> None:
        task = asyncio.create_task(self.handle_response(response))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def handle_response(self, response: Response) -> None:
        path = urlsplit(response.url).path
        if (
            path != SELLER_ORDER_PATH
            and path != SELLER_EXPORT_DOWNLOAD_PATH
            and path not in self._raw_only_paths
        ):
            return
        if response.status != 200:
            _log("seller_capture_failed", path=path, status=response.status)
            return
        try:
            payload = await response.json()
            if not isinstance(payload, Mapping):
                raise SellerOrderParseError("Response JSON must be an object")
            if payload.get("code") not in (None, 0, "0"):
                raise SellerOrderParseError("Response code is not zero")
            if path == SELLER_EXPORT_DOWNLOAD_PATH:
                await self._ingest_export_download(response, payload)
            else:
                async with self._lock:
                    if path == SELLER_ORDER_PATH:
                        await self._ingest_orders(response, payload)
                    else:
                        await self._retain_aggregate(path, payload)
                if self._raw_only_paths.get(path) == "seller_video_analytics":
                    await self._request_video_completions(response, payload)
                if path == SELLER_PRODUCT_LIST_PATH:
                    await self._product_catalog.request_remaining(response, payload)
        except Exception as error:  # noqa: BLE001 -- capture boundary records failure
            _log(
                "seller_capture_failed",
                path=path,
                error_type=type(error).__name__,
                error=str(error)[:300],
            )

    async def _ingest_orders(
        self,
        response: Response,
        payload: Mapping[str, object],
    ) -> None:
        external_shop_id = platform_shop_id(response.url)
        if not external_shop_id:
            _log("seller_order_rejected", reason="missing_platform_shop_id")
            return
        shop_id = self._shop_ids.get(external_shop_id)
        if shop_id is None:
            shop_id = await self._sync_repository.resolve_shop_id(
                self._tenant_id,
                external_shop_id,
            )
            if shop_id is None:
                _log("seller_order_rejected", reason="shop_not_found")
                return
            self._shop_ids[external_shop_id] = shop_id
        records = parse_seller_order_response(payload)
        result = await self._sync_repository.ingest_orders(
            self._tenant_id,
            shop_id,
            records,
        )
        _log(
            "seller_order_evidence_synced",
            shop_id=shop_id,
            received=len(records),
            evidence=result.evidence_count,
            attributions=result.attribution_count,
            unmatched=result.unmatched_count,
        )

    async def _retain_aggregate(
        self,
        path: str,
        payload: Mapping[str, object],
    ) -> None:
        data_type = self._raw_only_paths[path]
        records = (
            parse_video_completion_response(payload)
            if data_type == SELLER_VIDEO_COMPLETION_DATA_TYPE
            else parse_aggregate_response(payload, data_type=data_type)
        )
        result = await self._raw_repository.bulk_upsert(self._tenant_id, records)
        _log(
            "seller_aggregate_retained",
            path=path,
            data_type=data_type,
            raw_upserted=result.upserted_count,
            attribution_evidence_created=0,
        )

    async def _request_video_completions(
        self,
        response: Response,
        payload: Mapping[str, object],
    ) -> None:
        now = asyncio.get_running_loop().time()
        requested = 0
        for video_id in seller_video_ids(payload):
            last_requested_at = self._completion_requested_at.get(video_id)
            if last_requested_at is not None and now - last_requested_at < 1800:
                continue
            self._completion_requested_at[video_id] = now
            try:
                status = await response.frame.page.evaluate(
                    """async ({baseUrl, path, videoId}) => {
                        const url = new URL(baseUrl);
                        url.pathname = path;
                        for (const key of ['X-Bogus', 'X-Gnarly', 'msToken']) {
                            url.searchParams.delete(key);
                        }
                        const result = await fetch(url.toString(), {
                            method: 'POST', credentials: 'include',
                            headers: {'content-type': 'application/json'},
                            body: JSON.stringify({request: {params: [{item_id: videoId}]}})
                        });
                        return result.status;
                    }""",
                    {
                        "baseUrl": response.url,
                        "path": SELLER_VIDEO_COMPLETION_PATH,
                        "videoId": video_id,
                    },
                )
                if status != 200:
                    raise SellerOrderParseError("Video completion request failed")
                requested += 1
            except Exception as error:  # noqa: BLE001 -- continue other completions
                self._completion_requested_at.pop(video_id, None)
                _log(
                    "seller_video_completion_failed",
                    error_type=type(error).__name__,
                    error=str(error)[:300],
                )
        if requested:
            _log("seller_video_completion_requested", count=requested)

    async def _ingest_export_download(
        self,
        response: Response,
        payload: Mapping[str, object],
    ) -> None:
        data = payload.get("data")
        download_url = data.get("download_url") if isinstance(data, Mapping) else None
        if not isinstance(download_url, str):
            raise SellerOrderParseError("Export response has no download URL")
        download_split = urlsplit(download_url)
        hostname = (download_split.hostname or "").lower()
        if (
            download_split.scheme != "https"
            or not hostname.endswith(".tiktokglobalshop.com")
            or not download_split.path.startswith(SELLER_EXPORT_FILE_PREFIX)
        ):
            raise SellerOrderParseError("Export download URL is not allow-listed")
        external_shop_id = platform_shop_id(response.url)
        if not external_shop_id:
            raise SellerOrderParseError("Export response has no platform shop ID")
        shop_id = self._shop_ids.get(external_shop_id)
        if shop_id is None:
            shop_id = await self._sync_repository.resolve_shop_id(
                self._tenant_id,
                external_shop_id,
            )
            if shop_id is None:
                raise SellerOrderParseError("Export shop is not registered")
            self._shop_ids[external_shop_id] = shop_id
        _log("seller_export_download_registered", shop_id=shop_id)
        if len(self._export_downloads) >= 100:
            self._export_downloads.pop(next(iter(self._export_downloads)))
        self._export_downloads[_download_key(download_url)] = shop_id

    async def handle_export_route(self, route: Route) -> None:
        key = _download_key(route.request.url)
        shop_id = None
        for _ in range(50):
            shop_id = self._export_downloads.pop(key, None)
            if shop_id is not None:
                break
            await asyncio.sleep(0.05)
        if shop_id is None:
            await route.continue_()
            return
        content_size = 0
        route_finished = False
        try:
            upstream = await route.fetch()
            content = await upstream.body()
            await route.fulfill(response=upstream, body=content)
            route_finished = True
            content_size = len(content)
            if content_size > MAX_EXPORT_BYTES:
                raise SellerOrderParseError("Export exceeds safe size limit")
            if content.startswith(b"PK\x03\x04"):
                _log("seller_export_skipped", shop_id=shop_id, format="xlsx")
                return
            records = parse_seller_order_export(content)
            async with self._lock:
                result = await self._sync_repository.ingest_export(
                    self._tenant_id,
                    shop_id,
                    records,
                )
        except Exception as error:  # noqa: BLE001 -- export boundary records failure
            _log(
                "seller_export_failed",
                shop_id=shop_id,
                bytes=content_size,
                error_type=type(error).__name__,
                error=str(error)[:300],
            )
            if not route_finished:
                await route.continue_()
            return
        _log(
            "seller_export_evidence_synced",
            shop_id=shop_id,
            received=len(records),
            evidence=result.evidence_count,
            attributions=result.attribution_count,
            unmatched=result.unmatched_count,
        )

    async def wait_for_pending(self) -> None:
        if self._tasks:
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)


def _download_key(url: str) -> tuple[str, str]:
    return (((split := urlsplit(url)).hostname or "").lower(), split.path)
