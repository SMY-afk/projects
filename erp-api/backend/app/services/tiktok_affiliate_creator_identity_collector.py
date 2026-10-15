from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from datetime import date
from urllib.parse import parse_qs, urlsplit

from playwright.async_api import Page, Response

from backend.app.services.capture_logging import capture_log as _log
from backend.app.services.tiktok_affiliate_analytics_page_control import (
    PAGINATION_STATE_SCRIPT,
    current_and_next,
    is_affiliate_host,
)
from erp_api.services.affiliate_center_metric_dtos import AffiliateCreatorMetricDTO
from erp_api.services.affiliate_center_payload_contract import (
    AffiliatePayloadDiscriminatorError,
    require_affiliate_payload,
)
from erp_api.services.affiliate_creator_detail_backfill_repository import (
    CreatorDetailBackfillTarget,
)
from erp_api.services.affiliate_creator_metric_parser import (
    parse_creator_page_payload,
)

HOST = "affiliate.tiktokshopglobalselling.com"
PAGE_PATH = "/data/creator-analysis"
_LIST_PATH = "/api/v2/insights/affiliate/seller/creator/filter_list"
DATE_RANGE = ".m4b-date-picker-range"
_PAGINATION = ".kora-pagination-item:visible"


class CreatorDetailBackfillError(RuntimeError):
    pass


async def collect_creator_identities(
    page: Page,
    target: CreatorDetailBackfillTarget,
    tenant_id,
    *,
    max_pages: int,
    request_interval: float,
) -> list[AffiliateCreatorMetricDTO]:
    records_by_id: dict[str, AffiliateCreatorMetricDTO] = {}
    payload = await _load_first_page(page, target)
    expected_total: int | None = None
    for page_number in range(1, max_pages + 1):
        records = parse_creator_page_payload(payload, query=target.query)
        for record in records:
            creator_id = record.source_identifiers.get("tiktok_page_creator_id")
            if creator_id:
                records_by_id[creator_id] = record
        has_more, total = pagination(payload)
        expected_total = total if total is not None else expected_total
        if page_number == 1 or page_number % 10 == 0:
            _log(
                "affiliate_creator_detail_identity_page_captured",
                tenant_id=tenant_id,
                shop_id=target.query.shop_id,
                pages_fetched=page_number,
                records_unique=len(records_by_id),
                expected_total=expected_total,
            )
        if not has_more:
            if expected_total is not None and len(records_by_id) != expected_total:
                raise CreatorDetailBackfillError("creator_total_mismatch")
            _log(
                "affiliate_creator_detail_identities_collected",
                tenant_id=tenant_id,
                shop_id=target.query.shop_id,
                records_unique=len(records_by_id),
                expected_total=expected_total,
            )
            return list(records_by_id.values())
        await asyncio.sleep(request_interval)
        items = await page.locator(_PAGINATION).evaluate_all(PAGINATION_STATE_SCRIPT)
        current, next_index = current_and_next(items)
        if current != page_number or next_index is None:
            raise CreatorDetailBackfillError("creator_cursor_interrupted")
        payload = await _click_and_wait(page, next_index)
    raise CreatorDetailBackfillError("creator_max_pages_exceeded")


async def page_window(page: Page) -> tuple[date, date] | None:
    inputs = page.locator(f"{DATE_RANGE} input")
    if await inputs.count() < 2:
        return None
    current = [await inputs.nth(index).input_value() for index in range(2)]
    try:
        return date.fromisoformat(current[0]), date.fromisoformat(current[1])
    except ValueError:
        return None


def page_platform_shop_id(url: str) -> str:
    values = parse_qs(urlsplit(url).query).get("shop_id")
    return values[0].strip() if values else ""


def pagination(payload: Mapping[str, object]) -> tuple[bool, int | None]:
    try:
        segment = payload["data"]["segments"][0]
        control = segment["list_control"]["next_pagination"]
        total = control.get("total")
        return bool(control["has_more"]), total if isinstance(total, int) else None
    except (KeyError, IndexError, TypeError) as error:
        raise CreatorDetailBackfillError("creator_pagination_changed") from error


async def _load_first_page(
    page: Page, target: CreatorDetailBackfillTarget
) -> Mapping[str, object]:
    items = await page.locator(_PAGINATION).evaluate_all(PAGINATION_STATE_SCRIPT)
    current, _ = current_and_next(items)
    if current != 1:
        return await _click_and_wait(page, _first_page_index(items))
    payload = await _perform_and_wait(
        page, lambda: page.reload(wait_until="domcontentloaded")
    )
    if await page_window(page) != (
        target.query.window_start,
        target.query.window_end,
    ):
        raise CreatorDetailBackfillError("creator_window_changed")
    return payload


async def _click_and_wait(page: Page, index: int) -> Mapping[str, object]:
    return await _perform_and_wait(page, page.locator(_PAGINATION).nth(index).click)


async def _perform_and_wait(
    page: Page, action: Callable[[], Awaitable[object]]
) -> Mapping[str, object]:
    queue: asyncio.Queue[Mapping[str, object] | Exception] = asyncio.Queue()
    tasks: set[asyncio.Task[None]] = set()

    async def inspect(response: Response) -> None:
        split = urlsplit(response.url)
        if (
            not is_affiliate_host(split.hostname)
            or split.path != _LIST_PATH
            or response.request.method.upper() != "POST"
        ):
            return
        if response.status in {401, 403, 429}:
            await queue.put(CreatorDetailBackfillError(f"http_{response.status}"))
            return
        try:
            content_type = await response.header_value("content-type") or ""
            if response.status != 200 or not content_type.casefold().startswith(
                "application/json"
            ):
                return
            payload = await response.json()
            require_affiliate_payload("creators", payload)
            assert isinstance(payload, Mapping)
            await queue.put(payload)
        except AffiliatePayloadDiscriminatorError:
            return

    def schedule(response: Response) -> None:
        task = asyncio.create_task(inspect(response))
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    page.on("response", schedule)
    try:
        await action()
        result = await asyncio.wait_for(queue.get(), timeout=30)
        if isinstance(result, Exception):
            raise result
        return result
    except TimeoutError as error:
        raise CreatorDetailBackfillError("creator_request_timeout") from error
    finally:
        page.remove_listener("response", schedule)
        for task in tuple(tasks):
            task.cancel()
        if tasks:
            await asyncio.gather(*tuple(tasks), return_exceptions=True)


def _first_page_index(items: object) -> int:
    if isinstance(items, list):
        for index, item in enumerate(items):
            if isinstance(item, Mapping) and item.get("text") == "1":
                return index
    raise CreatorDetailBackfillError("creator_first_page_missing")
