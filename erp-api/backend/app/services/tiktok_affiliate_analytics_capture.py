from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from urllib.parse import urlsplit

from playwright.async_api import Page, Response

from backend.app.services.capture_logging import capture_log as _log
from backend.app.services.tiktok_affiliate_analytics_context import (
    AffiliateAnalyticsResponseContext,
)
from backend.app.services.tiktok_affiliate_analytics_page_control import (
    is_affiliate_host,
)
from backend.app.services.tiktok_affiliate_api_replay import replay_headers
from backend.app.services.tiktok_affiliate_contract import platform_shop_id
from erp_api.services.affiliate_center_capture_policy import (
    validate_capture_log_fields,
)
from erp_api.services.affiliate_center_contract_observer import (
    ContractObservationError,
    observe_response_contract,
)
from erp_api.services.affiliate_center_payload_contract import (
    is_creator_identity_only_payload,
)

CREATOR_ANALYTICS_PATH = "/api/v2/insights/affiliate/seller/creator/filter_list"
VIDEO_ANALYTICS_PATH = "/api/v1/oec/affiliate/compass/transaction/detail_list/get"
_RESOURCE_BY_PATH = {
    CREATOR_ANALYTICS_PATH: "creators",
    VIDEO_ANALYTICS_PATH: "videos",
}
_REQUEST_ID_HEADERS = (
    "request-id",
    "x-request-id",
    "x-tt-logid",
    "x-tt-trace-id",
)

AffiliateAnalyticsPayloadHandler = Callable[
    [
        Page,
        str,
        Mapping[str, object],
        dict[str, object],
        AffiliateAnalyticsResponseContext,
    ],
    Awaitable[None],
]
AffiliateAnalyticsFailureHandler = Callable[
    [Page | None, str, str, str], Awaitable[None]
]


class TikTokAffiliateAnalyticsSynchronizer:
    """Accept only confirmed affiliate analytics responses in the CDP session."""

    def __init__(
        self,
        mutation_lock: asyncio.Lock,
        payload_handler: AffiliateAnalyticsPayloadHandler | None = None,
        failure_handler: AffiliateAnalyticsFailureHandler | None = None,
    ) -> None:
        self._mutation_lock = mutation_lock
        self._payload_handler = payload_handler
        self._failure_handler = failure_handler
        self._tasks: set[asyncio.Task[None]] = set()
        self._latest_observations: dict[str, dict[str, object]] = {}

    @property
    def mutation_lock(self) -> asyncio.Lock:
        return self._mutation_lock

    def schedule_response(self, response: Response) -> None:
        task = asyncio.create_task(self.handle_response(response))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def handle_response(self, response: Response) -> None:
        split = urlsplit(response.url)
        method = response.request.method.upper()
        resource = _RESOURCE_BY_PATH.get(split.path)
        if (
            not is_affiliate_host(split.hostname)
            or method != "POST"
            or resource is None
        ):
            return

        page = _response_page(response)
        if response.status != 200:
            failure_status, failure_category = _http_failure(response.status)
            await self._notify_failure(
                page,
                resource,
                failure_status,
                failure_category,
            )
            _capture_log(
                {
                    401: "affiliate_analytics_http_session_expired",
                    403: "affiliate_analytics_http_forbidden",
                    429: "affiliate_analytics_http_rate_limited",
                }.get(response.status, "affiliate_analytics_http_failed")
            )
            _capture_log(
                "affiliate_analytics_response_rejected",
            )
            return

        try:
            headers = await _allowed_response_headers(response)
            content_type = headers.get("content-type")
            if not (content_type or "").casefold().startswith("application/json"):
                await self._notify_failure(
                    page,
                    resource,
                    "failed",
                    "payload_content_type_changed",
                )
                _capture_log(
                    "affiliate_analytics_response_rejected",
                    request_id=_first_header_request_id(headers),
                )
                return
            payload = await response.json()
            observation = observe_response_contract(
                resource=resource,
                url=response.url,
                method=method,
                status=response.status,
                response_headers=headers,
                payload=payload,
            )
        except ContractObservationError:
            if resource == "creators" and is_creator_identity_only_payload(payload):
                _capture_log("affiliate_analytics_response_ignored")
                return
            await self._notify_failure(
                page,
                resource,
                "failed",
                "payload_structure_changed",
            )
            _capture_log(
                "affiliate_analytics_response_rejected",
            )
            return
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 -- response boundary
            await self._notify_failure(
                page,
                resource,
                "failed",
                "payload_read_failed",
            )
            _capture_log(
                "affiliate_analytics_response_failed",
            )
            return

        assert isinstance(payload, Mapping)
        if self._payload_handler is not None and page is None:
            await self._notify_failure(
                page,
                resource,
                "failed",
                "page_context_unavailable",
            )
            _capture_log(
                "affiliate_analytics_response_failed",
            )
            return
        try:
            async with self._mutation_lock:
                if self._payload_handler is not None:
                    assert page is not None
                    await self._payload_handler(
                        page,
                        resource,
                        payload,
                        observation,
                        AffiliateAnalyticsResponseContext(
                            platform_shop_id(response.url),
                            _first_request_id(observation),
                            request_url=response.url,
                            request_headers=replay_headers(
                                getattr(response.request, "headers", {})
                            ),
                            request_body=_request_body(response),
                        ),
                    )
                self._latest_observations[resource] = observation
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 -- handler boundary
            await self._notify_failure(
                page,
                resource,
                "failed",
                "payload_handler_failed",
            )
            _capture_log(
                "affiliate_analytics_response_failed",
            )
            return

        _capture_log(
            "affiliate_analytics_response_accepted",
            request_id=_first_request_id(observation),
        )

    async def wait_for_pending(self) -> None:
        if self._tasks:
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)

    async def _notify_failure(
        self,
        page: Page | None,
        resource: str,
        status: str,
        category: str,
    ) -> None:
        if self._failure_handler is None:
            return
        try:
            async with self._mutation_lock:
                await self._failure_handler(page, resource, status, category)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 -- failure reporting boundary
            _capture_log(
                "affiliate_analytics_failure_handler_failed",
            )


async def _allowed_response_headers(response: Response) -> dict[str, str]:
    result: dict[str, str] = {}
    for name in ("content-type", *_REQUEST_ID_HEADERS):
        value = await response.header_value(name)
        if value is not None:
            result[name] = value
    return result


def _first_request_id(observation: Mapping[str, object]) -> str | None:
    request_ids = observation.get("requestIds")
    if not isinstance(request_ids, list) or not request_ids:
        return None
    first = request_ids[0]
    if not isinstance(first, Mapping):
        return None
    value = first.get("value")
    return value if isinstance(value, str) else None


def _first_header_request_id(headers: Mapping[str, str]) -> str | None:
    return next(
        (headers[name] for name in _REQUEST_ID_HEADERS if headers.get(name)),
        None,
    )


def _response_page(response: Response) -> Page | None:
    try:
        return response.request.frame.page
    except Exception:  # noqa: BLE001 -- service-worker responses have no frame
        return None


def _request_body(response: Response) -> Mapping[str, object] | None:
    value = getattr(response.request, "post_data_json", None)
    return value if isinstance(value, Mapping) else None


def _http_failure(status: int) -> tuple[str, str]:
    if status == 401:
        return "session_required", "session_expired"
    if status == 403:
        return "failed", "http_403"
    if status == 429:
        return "failed", "rate_limited"
    return "failed", "http_status"


def _capture_log(event: str, **values: object) -> None:
    safe = validate_capture_log_fields({"event": event, **values})
    safe.pop("event")
    _log(event, **safe)
