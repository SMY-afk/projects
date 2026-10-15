from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from urllib.parse import urlsplit

from playwright.async_api import Page, Response

from backend.app.services.capture_logging import capture_log
from backend.app.services.tiktok_affiliate_analytics_page_control import (
    is_affiliate_host,
)
from backend.app.services.tiktok_affiliate_creator_identity_collector import (
    CreatorDetailBackfillError,
    _perform_and_wait,
    pagination,
)
from erp_api.services.affiliate_center_contract import AffiliateCenterQuery
from erp_api.services.affiliate_center_metric_dtos import AffiliateCreatorMetricDTO
from erp_api.services.affiliate_center_payload_contract import require_affiliate_payload
from erp_api.services.affiliate_creator_metric_parser import (
    parse_creator_page_payload,
)

_LIST_PATH = "/api/v2/insights/affiliate/seller/creator/filter_list"
_BATCH_PAGE_SIZE = 200
LIST_RESPONSE_TIMEOUT_SECONDS = 30
_BATCH_FETCH_SCRIPT = """
async (arg) => {
  const response = await fetch(arg.url, {
    method: 'POST',
    credentials: 'include',
    headers: {'content-type': 'application/json'},
    body: JSON.stringify(arg.body),
  });
  return {status: response.status, payload: await response.json()};
}
"""


@dataclass(frozen=True)
class CreatorIdentitySample:
    records: list[AffiliateCreatorMetricDTO]
    expected_total: int | None


@dataclass(frozen=True)
class CreatorIdentitySource:
    request_url: str
    request_body: Mapping[str, object]
    first_payload: Mapping[str, object]
    expected_total: int


def creator_identity_page_limit(expected_total: int) -> int:
    if expected_total < 0:
        raise ValueError("expected_total cannot be negative")
    return max(30, (expected_total + _BATCH_PAGE_SIZE - 1) // _BATCH_PAGE_SIZE)


async def creator_source_total(
    page: Page,
    trigger: Callable[[], Awaitable[None]],
) -> int:
    payload = await _perform_and_wait(page, trigger)
    _has_more, total = pagination(payload)
    if total is None:
        raise CreatorDetailBackfillError("creator_total_missing")
    return total


async def prepare_creator_identity_source(
    page: Page,
    trigger: Callable[[], Awaitable[None]],
) -> CreatorIdentitySource:
    request_url, request_body = await _list_request(page, trigger)
    first_payload = await _fetch_identity_batch(
        page,
        request_url,
        _batch_request_body(request_body, 0),
    )
    _has_more, expected_total = pagination(first_payload)
    if expected_total is None:
        raise CreatorDetailBackfillError("creator_total_missing")
    return CreatorIdentitySource(
        request_url=request_url,
        request_body=request_body,
        first_payload=first_payload,
        expected_total=expected_total,
    )


async def collect_creator_identity_sample(
    page: Page,
    query: AffiliateCenterQuery,
    tenant_id,
    *,
    max_pages: int,
    request_interval: float,
    target_usernames: frozenset[str] = frozenset(),
    trigger: Callable[[], Awaitable[None]] | None = None,
    collect_all: bool = False,
    source: CreatorIdentitySource | None = None,
) -> CreatorIdentitySample:
    records_by_username: dict[str, AffiliateCreatorMetricDTO] = {}
    if source is None:
        request_url, request_body = await _list_request(page, trigger)
        first_payload = None
    else:
        request_url = source.request_url
        request_body = source.request_body
        first_payload = source.first_payload
    source_total: int | None = None
    for page_number in range(1, max_pages + 1):
        if page_number == 1 and first_payload is not None:
            payload = first_payload
        else:
            payload = await _fetch_identity_batch(
                page,
                request_url,
                _batch_request_body(request_body, page_number - 1),
            )
        for record in parse_creator_page_payload(payload, query=query):
            if collect_all or record.avatar_url:
                records_by_username[record.username_normalized] = record
        has_more, expected_total = pagination(payload)
        if expected_total is not None:
            source_total = expected_total
        if (
            (not collect_all and target_usernames.issubset(records_by_username))
            or not has_more
            or page_number == max_pages
        ):
            capture_log(
                "affiliate_creator_avatar_sample_collected",
                tenant_id=tenant_id,
                shop_id=query.shop_id,
                pages_fetched=page_number,
                records_unique=len(records_by_username),
                expected_total=source_total,
            )
            return CreatorIdentitySample(
                records=list(records_by_username.values()),
                expected_total=source_total,
            )
        await asyncio.sleep(request_interval)
    return CreatorIdentitySample(list(records_by_username.values()), source_total)


async def _list_request(
    page: Page,
    trigger: Callable[[], Awaitable[None]] | None,
) -> tuple[str, Mapping[str, object]]:
    queue: asyncio.Queue[tuple[str, Mapping[str, object]] | Exception] = asyncio.Queue()
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
            payload = await response.json()
            require_affiliate_payload("creators", payload)
            body = response.request.post_data_json
            if isinstance(body, Mapping):
                await queue.put((response.url, body))
        except Exception:  # noqa: BLE001 -- skip transitional identity responses
            return

    def schedule(response: Response) -> None:
        task = asyncio.create_task(inspect(response))
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    page.on("response", schedule)
    try:
        action = trigger or (lambda: page.reload(wait_until="domcontentloaded"))
        await action()
        try:
            result = await asyncio.wait_for(
                queue.get(), timeout=LIST_RESPONSE_TIMEOUT_SECONDS
            )
        except TimeoutError:
            await page.evaluate("location.reload()")
            result = await asyncio.wait_for(
                queue.get(), timeout=LIST_RESPONSE_TIMEOUT_SECONDS
            )
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


def _batch_request_body(
    request_body: Mapping[str, object], page_index: int
) -> dict[str, object]:
    try:
        result = deepcopy(dict(request_body))
        pagination = result["request"]["requests"][0]["list_control"]["pagination"]
        pagination["size"] = _BATCH_PAGE_SIZE
        pagination["page"] = page_index
        return result
    except (KeyError, IndexError, TypeError) as error:
        raise CreatorDetailBackfillError("creator_request_changed") from error


async def _fetch_identity_batch(
    page: Page,
    request_url: str,
    request_body: Mapping[str, object],
) -> Mapping[str, object]:
    try:
        result = await page.evaluate(
            _BATCH_FETCH_SCRIPT,
            {"url": request_url, "body": request_body},
        )
        if not isinstance(result, Mapping) or result.get("status") != 200:
            raise TypeError("Creator list batch request failed.")
        payload = result.get("payload")
        require_affiliate_payload("creators", payload)
        if not isinstance(payload, Mapping):
            raise TypeError("Creator list batch payload is unavailable.")
        return payload
    except Exception as error:
        raise CreatorDetailBackfillError("creator_request_failed") from error
