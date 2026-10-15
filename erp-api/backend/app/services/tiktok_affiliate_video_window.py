from __future__ import annotations

import asyncio
import copy
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from urllib.parse import urlsplit

from playwright.async_api import Page, Request, Response

from backend.app.services.tiktok_affiliate_analytics_page_control import (
    RESOURCE_ENDPOINT,
    capture_log,
)
from backend.app.services.tiktok_affiliate_api_replay import AffiliateApiReplay
from erp_api.services.affiliate_center_contract import (
    AffiliateCenterQuery,
    AffiliateCenterResource,
)

_RESPONSE_TIMEOUT_MS = 30_000
_TEMPLATE_SETTLE_SECONDS = 1.0


class VideoWindowControlError(RuntimeError):
    pass


@dataclass
class _DataApiTrigger:
    page: Page
    query: AffiliateCenterQuery
    route_state: dict[str, int]
    replay: AffiliateApiReplay

    async def __call__(self) -> None:
        await self.request_page(1)

    def current_page(self) -> int:
        return self.route_state["page_number"]

    async def request_page(self, page_number: int) -> None:
        if page_number < 1:
            raise VideoWindowControlError("window_not_settable")
        self.route_state["page_number"] = page_number
        try:
            template = self.replay.template_body
            if template is None:
                raise VideoWindowControlError("window_not_settable")
            body = _rewrite_request_window(
                template,
                self.query,
                page_number=page_number,
            )
            status = await self.replay.post(body)
            if status != 200:
                raise VideoWindowControlError("window_not_settable")
        except VideoWindowControlError:
            raise
        except Exception as error:
            raise VideoWindowControlError("window_not_settable") from error

    async def cleanup(self) -> None:
        return None


async def prepare_video_window_trigger(
    page: Page,
    query: AffiliateCenterQuery,
    *,
    replay: AffiliateApiReplay | None = None,
    after_reload: Callable[[], Awaitable[None]] | None = None,
) -> _DataApiTrigger:
    api_replay = replay or AffiliateApiReplay(page)
    if api_replay.template_body is None:
        await _capture_api_template(
            page,
            query,
            api_replay,
            after_reload=after_reload,
        )
    return _DataApiTrigger(page, query, {"page_number": 1}, api_replay)


async def _capture_api_template(
    page: Page,
    query: AffiliateCenterQuery,
    replay: AffiliateApiReplay,
    *,
    after_reload: Callable[[], Awaitable[None]] | None = None,
) -> None:
    endpoint = RESOURCE_ENDPOINT[query.resource.value]
    ready = asyncio.Event()
    response_ready = asyncio.Event()
    tasks: set[asyncio.Task[None]] = set()
    template_request: Request | None = None
    completed_requests: list[Request] = []

    async def capture(request: Request) -> None:
        nonlocal template_request
        try:
            body = request.post_data_json
            _rewrite_request_window(body, query, page_number=1)
            assert isinstance(body, dict)
            await replay.capture(request, body)
        except Exception:  # noqa: BLE001 -- ignore unrelated endpoint variants
            return
        template_request = request
        ready.set()
        if any(candidate is request for candidate in completed_requests):
            response_ready.set()

    def observe(request: Request) -> None:
        if urlsplit(request.url).path != endpoint or request.method.upper() != "POST":
            return
        task = asyncio.create_task(capture(request))
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    def observe_response(response: Response) -> None:
        request = response.request
        if urlsplit(request.url).path != endpoint or request.method.upper() != "POST":
            return
        completed_requests.append(request)
        if request is template_request:
            response_ready.set()

    page.on("request", observe)
    page.on("response", observe_response)
    try:
        await page.reload(
            wait_until="domcontentloaded",
            timeout=_RESPONSE_TIMEOUT_MS,
        )
        if after_reload is not None:
            await after_reload()
        await asyncio.wait_for(ready.wait(), timeout=_RESPONSE_TIMEOUT_MS / 1000)
        await asyncio.wait_for(
            response_ready.wait(), timeout=_RESPONSE_TIMEOUT_MS / 1000
        )
        await asyncio.sleep(_TEMPLATE_SETTLE_SECONDS)
        capture_log("affiliate_data_api_template_captured")
    except Exception as error:
        raise VideoWindowControlError("window_not_settable") from error
    finally:
        page.remove_listener("request", observe)
        page.remove_listener("response", observe_response)
        if tasks:
            await asyncio.gather(*tuple(tasks), return_exceptions=True)


def _rewrite_request_window(
    body: object,
    query: AffiliateCenterQuery,
    *,
    page_number: int | None = None,
) -> dict[str, object]:
    if not isinstance(body, Mapping):
        raise VideoWindowControlError("window_not_settable")
    rewritten = copy.deepcopy(dict(body))
    if query.resource is AffiliateCenterResource.CREATORS:
        _rewrite_creator_window(rewritten, query, page_number)
    else:
        _rewrite_video_window(rewritten, query, page_number)
    return rewritten


def _rewrite_creator_window(
    body: dict[str, object],
    query: AffiliateCenterQuery,
    page_number: int | None,
) -> None:
    request = _mapping(body.get("request"))
    requests = _one_item_list(request.get("requests"))
    descriptor = _mapping(requests[0].get("time_descriptor"))
    descriptor["start"] = query.window_start.isoformat()
    descriptor["end"] = (query.window_end + timedelta(days=1)).isoformat()
    days = (query.window_end - query.window_start).days + 1
    descriptor["granularity"] = f"{days}D"
    control = _mapping(requests[0].get("list_control"))
    pagination = _mapping(control.get("pagination"))
    pagination["size"] = 10
    if page_number is not None:
        pagination["page"] = page_number - 1


def _rewrite_video_window(
    body: dict[str, object],
    query: AffiliateCenterQuery,
    page_number: int | None,
) -> None:
    params = _mapping(body.get("params"))
    lists = _one_item_list(params.get("video_list_params_v2"))
    descriptor = _mapping(lists[0].get("time_descriptor"))
    offset = _offset_seconds(descriptor.get("timezone_offset"))
    scale = 1000 if _numeric(descriptor.get("start_time")) > 10_000_000_000 else 1
    descriptor["start_time"] = _local_midnight_epoch(query.window_start, offset) * scale
    descriptor["end_time"] = (
        _local_midnight_epoch(query.window_end + timedelta(days=1), offset) * scale
    )
    days = (query.window_end - query.window_start).days + 1
    descriptor["time_option_type"] = 1 if days <= 2 else 4
    page_param = _mapping(lists[0].get("page_param"))
    if page_number is not None:
        page_param["page_no"] = page_number


def _request_matches_query_window(
    body: object,
    query: AffiliateCenterQuery,
) -> bool:
    try:
        if query.resource is AffiliateCenterResource.CREATORS:
            request = _mapping(_mapping(body).get("request"))
            segment = _one_item_list(request.get("requests"))[0]
            descriptor = _mapping(segment.get("time_descriptor"))
            return (descriptor.get("start"), descriptor.get("end")) == (
                query.window_start.isoformat(),
                (query.window_end + timedelta(days=1)).isoformat(),
            )
        root = _mapping(body)
        export_segment = root.get("transaction_video_list_params_v2")
        if isinstance(export_segment, dict):
            segment = export_segment
        else:
            params = _mapping(root.get("params"))
            segment = _one_item_list(params.get("video_list_params_v2"))[0]
        descriptor = _mapping(segment.get("time_descriptor"))
        offset = _offset_seconds(descriptor.get("timezone_offset"))
        scale = 1000 if _numeric(descriptor.get("start_time")) > 10_000_000_000 else 1
        start = int(_numeric(descriptor.get("start_time")) / scale)
        end = int(_numeric(descriptor.get("end_time")) / scale)
        return (
            datetime.fromtimestamp(start + offset, tz=UTC).date(),
            datetime.fromtimestamp(end + offset, tz=UTC).date(),
        ) == (query.window_start, query.window_end + timedelta(days=1))
    except (TypeError, ValueError, OSError, OverflowError, VideoWindowControlError):
        return False


def _local_midnight_epoch(value: date, offset_seconds: int) -> int:
    utc_midnight = datetime.combine(value, time.min, tzinfo=UTC)
    return int(utc_midnight.timestamp()) - offset_seconds


def _offset_seconds(value: object) -> int:
    number = _numeric(value)
    seconds = number * 3600 if abs(number) <= 24 else number
    if seconds != int(seconds) or abs(seconds) > 14 * 3600:
        raise VideoWindowControlError("window_not_settable")
    return int(seconds)


def _numeric(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise VideoWindowControlError("window_not_settable")
    return float(value)


def _mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise VideoWindowControlError("window_not_settable")
    return value


def _one_item_list(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
        raise VideoWindowControlError("window_not_settable")
    return value
