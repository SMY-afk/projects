from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import UUID
from zoneinfo import ZoneInfo

from playwright.async_api import BrowserContext, Page

from app.parsers.seller_order_export_parser import (
    SellerOrderExportParseError,
    parse_seller_order_export,
)
from backend.app.services.capture_logging import capture_log as _log
from backend.app.services.capture_logging import safe_error as _safe_error
from backend.app.services.tiktok_affiliate_contract import platform_shop_id
from backend.app.services.tiktok_seller_capture import (
    MAX_EXPORT_BYTES,
    SELLER_EXPORT_FILE_PREFIX,
    SELLER_ORDER_PATH,
)
from backend.app.services.tiktok_seller_order_page import ensure_seller_order_page
from erp_api.services.seller_evidence_sync_repository import (
    SellerEvidenceSyncRepository,
)

SELLER_EXPORT_PATH = "/api/fulfillment/na/order/export"
SELLER_EXPORT_RECORD_PATH = "/api/fulfillment/na/order/export_record/get"
SELLER_EXPORT_DOWNLOAD_PATH = "/api/fulfillment/na/order/download"
SELLER_TIMEZONE = ZoneInfo("America/Los_Angeles")
_DYNAMIC_QUERY_KEYS = {"x-bogus", "x-gnarly", "mstoken"}


class TikTokSellerExportSynchronizer:
    """Create, download and ingest merchant-creator exports without user clicks."""

    def __init__(
        self,
        contexts: Sequence[BrowserContext],
        repository: SellerEvidenceSyncRepository,
        tenant_id: UUID,
        mutation_lock: asyncio.Lock,
        *,
        interval_seconds: float = 1800,
        lookback_days: int = 28,
        poll_interval_seconds: float = 2,
        timeout_seconds: float = 120,
    ) -> None:
        self._contexts = contexts
        self._repository = repository
        self._tenant_id = tenant_id
        self._lock = mutation_lock
        self._interval_seconds = interval_seconds
        self._lookback_days = lookback_days
        self._poll_interval_seconds = poll_interval_seconds
        self._timeout_seconds = timeout_seconds

    async def run(self, stopped: asyncio.Event) -> None:
        while not stopped.is_set():
            try:
                await self.sync_once()
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001 -- retry loop records failure
                _log(
                    "seller_export_auto_failed",
                    error_type=type(error).__name__,
                    error=_safe_error(error),
                    retry_in_seconds=self._interval_seconds,
                )
            try:
                await asyncio.wait_for(stopped.wait(), timeout=self._interval_seconds)
            except TimeoutError:
                continue

    async def sync_once(self) -> None:
        context, page = await ensure_seller_order_page(
            self._contexts,
            timeout_seconds=self._timeout_seconds,
        )
        order_api_url = await self._latest_order_api_url(page)
        external_shop_id = platform_shop_id(order_api_url)
        if not external_shop_id:
            raise SellerOrderExportParseError("Seller API URL has no shop ID")
        shop_id = await self._repository.resolve_shop_id(
            self._tenant_id,
            external_shop_id,
        )
        if shop_id is None:
            raise SellerOrderExportParseError("Seller export shop is not registered")

        request = build_seller_export_request(
            datetime.now(SELLER_TIMEZONE),
            lookback_days=self._lookback_days,
        )
        created = await self._post_json(
            page,
            seller_api_endpoint(order_api_url, SELLER_EXPORT_PATH),
            request,
        )
        task_id = _required_text(created, "export_task_id")
        record = await self._wait_for_export(page, order_api_url, task_id)
        file_key = _required_text(record, "file_key")
        download = await self._post_json(
            page,
            seller_api_endpoint(order_api_url, SELLER_EXPORT_DOWNLOAD_PATH),
            {"file_key": file_key, "export_task_id": task_id},
        )
        download_url = _required_text(download, "download_url")
        _validate_download_url(download_url)
        response = await context.request.get(
            download_url,
            timeout=self._timeout_seconds * 1000,
        )
        if response.status != 200:
            raise SellerOrderExportParseError(
                f"Seller export download returned HTTP {response.status}"
            )
        content = await response.body()
        if len(content) > MAX_EXPORT_BYTES:
            raise SellerOrderExportParseError("Export exceeds safe size limit")
        if content.startswith(b"PK\x03\x04"):
            raise SellerOrderExportParseError("Automatic export must be CSV")

        records = parse_seller_order_export(content)
        async with self._lock:
            result = await self._repository.ingest_export(
                self._tenant_id,
                shop_id,
                records,
            )
        _log(
            "seller_export_auto_synced",
            shop_id=shop_id,
            received=len(records),
            evidence=result.evidence_count,
            attributions=result.attribution_count,
            unmatched=result.unmatched_count,
            lookback_days=self._lookback_days,
        )

    async def _latest_order_api_url(self, page: Page) -> str:
        resource_url = await page.evaluate(
            """path => performance.getEntriesByType('resource')
                .map(entry => entry.name)
                .filter(url => { try { return new URL(url).pathname === path; }
                                 catch (_) { return false; } })
                .at(-1) || null""",
            SELLER_ORDER_PATH,
        )
        if isinstance(resource_url, str) and resource_url:
            return resource_url
        async with page.expect_request(
            lambda request: urlsplit(request.url).path == SELLER_ORDER_PATH,
            timeout=self._timeout_seconds * 1000,
        ) as request_info:
            await page.reload(wait_until="domcontentloaded")
        return (await request_info.value).url

    async def _wait_for_export(
        self,
        page: Page,
        order_api_url: str,
        task_id: str,
    ) -> Mapping[str, object]:
        deadline = asyncio.get_running_loop().time() + self._timeout_seconds
        record_url = seller_api_endpoint(order_api_url, SELLER_EXPORT_RECORD_PATH)
        while asyncio.get_running_loop().time() < deadline:
            data = await self._post_json(page, record_url, {})
            records = data.get("export_records")
            if isinstance(records, list):
                record = _find_export_record(records, task_id)
                if record is not None and _text(record.get("file_key")):
                    return record
            await asyncio.sleep(self._poll_interval_seconds)
        raise SellerOrderExportParseError("Seller export task timed out")

    @staticmethod
    async def _post_json(
        page: Page,
        url: str,
        body: Mapping[str, object],
    ) -> Mapping[str, object]:
        result = await page.evaluate(
            """async ({url, body}) => {
                const response = await fetch(url, {
                    method: 'POST',
                    credentials: 'include',
                    headers: {'content-type': 'application/json'},
                    body: JSON.stringify(body)
                });
                let payload = null;
                try { payload = await response.json(); } catch (_) {}
                return {status: response.status, payload};
            }""",
            {"url": url, "body": dict(body)},
        )
        status = result.get("status") if isinstance(result, Mapping) else None
        payload = result.get("payload") if isinstance(result, Mapping) else None
        if status != 200 or not isinstance(payload, Mapping):
            raise SellerOrderExportParseError("Seller export API request failed")
        if payload.get("code") not in (0, "0"):
            raise SellerOrderExportParseError("Seller export API rejected request")
        data = payload.get("data")
        if not isinstance(data, Mapping):
            raise SellerOrderExportParseError("Seller export API returned no data")
        return data


def build_seller_export_request(
    now: datetime,
    *,
    lookback_days: int,
) -> dict[str, object]:
    local_now = now.astimezone(SELLER_TIMEZONE)
    end = local_now.replace(hour=23, minute=59, second=59, microsecond=999000)
    start = (end - timedelta(days=lookback_days - 1)).replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )
    file_name = f"erp-merchant-creators-{local_now:%Y%m%d-%H%M%S}.csv"
    return {
        "search_condition": {
            "condition_list": {
                "order_source": {"value": ["1"]},
                "time_order_created": {
                    "value": [
                        str(int(start.timestamp() * 1000)),
                        str(int(end.timestamp() * 1000)),
                    ]
                },
            }
        },
        "sort_info": "6",
        "file_name": file_name,
        "file_type": 2,
    }


def seller_api_endpoint(resource_url: str, path: str) -> str:
    split = urlsplit(resource_url)
    query = [
        (key, value)
        for key, value in parse_qsl(split.query, keep_blank_values=True)
        if key.casefold() not in _DYNAMIC_QUERY_KEYS
    ]
    return urlunsplit((split.scheme, split.netloc, path, urlencode(query), ""))


def _find_export_record(
    records: Sequence[object],
    task_id: str,
) -> Mapping[str, object] | None:
    return next(
        (
            record
            for record in records
            if isinstance(record, Mapping)
            and _text(record.get("export_task_id")) == task_id
        ),
        None,
    )


def _validate_download_url(url: str) -> None:
    split = urlsplit(url)
    hostname = (split.hostname or "").lower()
    if (
        split.scheme != "https"
        or not hostname.endswith(".tiktokglobalshop.com")
        or not split.path.startswith(SELLER_EXPORT_FILE_PREFIX)
    ):
        raise SellerOrderExportParseError("Export download URL is not allow-listed")


def _required_text(value: Mapping[str, object], key: str) -> str:
    parsed = _text(value.get(key))
    if parsed is None:
        raise SellerOrderExportParseError(f"Seller export response has no {key}")
    return parsed


def _text(value: Any) -> str | None:
    if value is None or isinstance(value, (dict, list)):
        return None
    parsed = str(value).strip()
    return parsed or None
