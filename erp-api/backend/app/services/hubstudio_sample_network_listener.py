from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Iterable, Mapping
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

from playwright.async_api import BrowserContext, Response

from backend.app.services.capture_logging import capture_log as _log
from erp_api.services.affiliate_center_capture_policy import (
    validate_capture_log_fields,
)
from erp_api.services.hubstudio_sample_application_source import (
    HubStudioSamplePreflight,
)
from erp_api.services.hubstudio_sample_response_parser import (
    parse_hubstudio_sample_response,
)
from erp_api.services.hubstudio_sample_types import HubStudioSampleCapture
from erp_api.services.tiktok_sample_application_client import (
    SAMPLE_APPLICATION_SEARCH_PATH,
)

DEFAULT_SAMPLE_RESPONSE_HOSTS = frozenset(
    {
        "affiliate.tiktokshopglobalselling.com",
        "affiliate-us.tiktok.com",
        "open-api.tiktokglobalshop.com",
    }
)
CURRENT_SAMPLE_GROUP_LIST_PATH = "/api/v1/affiliate/sample/group/list"
DEFAULT_SAMPLE_RESPONSE_PATHS = frozenset(
    {SAMPLE_APPLICATION_SEARCH_PATH, CURRENT_SAMPLE_GROUP_LIST_PATH}
)
_REQUEST_ID_HEADERS = (
    "request-id",
    "x-request-id",
    "x-tts-request-id",
    "x-tt-logid",
    "x-tt-trace-id",
)


SampleCaptureHandler = Callable[[HubStudioSampleCapture], Awaitable[None]]
SampleStopHandler = Callable[[str], Awaitable[None]]
SampleSourceGuard = Callable[[], Awaitable[None]]
_AUTH_PATH_MARKERS = ("/login", "/passport", "/signin", "/auth/")


class HubStudioSampleNetworkListener:
    """Read only exact-whitelisted response bodies from an attached CDP session."""

    def __init__(
        self,
        preflight: HubStudioSamplePreflight,
        handler: SampleCaptureHandler,
        *,
        stop_handler: SampleStopHandler | None = None,
        source_guard: SampleSourceGuard | None = None,
        allowed_paths: frozenset[str] = DEFAULT_SAMPLE_RESPONSE_PATHS,
        allowed_hosts: frozenset[str] = DEFAULT_SAMPLE_RESPONSE_HOSTS,
    ) -> None:
        self._validate_paths(allowed_paths)
        self._validate_hosts(allowed_hosts)
        self._preflight = preflight
        self._handler = handler
        self._stop_handler = stop_handler
        self._source_guard = source_guard
        self._allowed_paths = allowed_paths
        self._allowed_hosts = frozenset(host.casefold() for host in allowed_hosts)
        self._tasks: set[asyncio.Task[None]] = set()
        self._handler_lock = asyncio.Lock()
        self._response_scheduled = False
        self._stopped = asyncio.Event()
        self._stop_reason: str | None = None

    @property
    def is_stopped(self) -> bool:
        return self._stopped.is_set()

    @property
    def stop_reason(self) -> str | None:
        return self._stop_reason

    def attach(self, contexts: Iterable[BrowserContext]) -> int:
        """Subscribe to response events on already-connected CDP contexts."""
        attached = 0
        for context in contexts:
            context.on("response", self.schedule_response)
            attached += 1
        return attached

    def schedule_response(self, response: Response) -> None:
        if (
            self.is_stopped
            or self._handler_lock.locked()
            or self._response_scheduled
        ):
            return
        split = urlsplit(response.url)
        if not self._matches(
            hostname=split.hostname,
            path=split.path,
            method=response.request.method,
        ):
            return
        if split.path == CURRENT_SAMPLE_GROUP_LIST_PATH and not _is_review_request_date(
            response.request.post_data,
        ):
            return
        self._response_scheduled = True
        task = asyncio.create_task(
            self.handle_response(response, observed_at=datetime.now(UTC))
        )
        self._tasks.add(task)
        task.add_done_callback(self._finish_scheduled_response)

    def _finish_scheduled_response(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        self._response_scheduled = False

    async def handle_response(
        self, response: Response, *, observed_at: datetime | None = None
    ) -> None:
        observed_at = observed_at or datetime.now(UTC)
        if self.is_stopped:
            return
        split = urlsplit(response.url)
        if not self._matches(
            hostname=split.hostname,
            path=split.path,
            method=response.request.method,
        ):
            return
        if split.path == CURRENT_SAMPLE_GROUP_LIST_PATH and not _is_review_request_date(
            response.request.post_data,
        ):
            return
        if self._source_guard is not None:
            try:
                await self._source_guard()
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001 -- source policy boundary
                code = getattr(error, "code", None)
                reason = (
                    code
                    if code in {"official_api_available", "official_api_reconciled"}
                    else "source_policy_failed"
                )
                await self._stop(reason)
                return
        if response.status in {401, 403}:
            await self._stop(
                "session_expired" if response.status == 401 else "http_403"
            )
            return
        page_url = _response_page_url(response)
        if _is_auth_page(page_url):
            await self._stop("session_expired")
            return
        if _page_shop_ids(page_url, response.url) != frozenset(
            {self._preflight.target.platform_shop_id}
        ):
            await self._stop("page_shop_mismatch")
            return
        if response.status != 200:
            self._log("hubstudio_sample_response_rejected")
            return

        request_id: str | None = None
        try:
            headers = await _allowed_response_headers(response)
            request_id = _first_request_id(headers)
            if not (headers.get("content-type") or "").casefold().startswith(
                "application/json"
            ):
                await self._stop("payload_structure_changed")
                return
            payload = await response.json()
            request_id = request_id or _body_request_id(payload)
            page = parse_hubstudio_sample_response(
                payload,
                platform_request_id=request_id,
                observed_at=observed_at,
            )
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 -- untrusted network response boundary
            await self._stop("payload_structure_changed")
            return

        try:
            async with self._handler_lock:
                if self.is_stopped:
                    return
                await self._handler(
                    HubStudioSampleCapture(
                        target=self._preflight.target,
                        page=page,
                        observed_at=observed_at,
                    )
                )
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 -- downstream persistence boundary
            await self._stop("ingest_failed")
            return

        self._log(
            "hubstudio_sample_response_accepted",
            request_id=request_id,
            records_received=len(page.applications),
        )

    async def wait_for_pending(self) -> None:
        if self._tasks:
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)

    async def wait_stopped(self) -> None:
        await self._stopped.wait()

    async def stop(self, reason: str) -> None:
        await self._stop(reason)

    async def _stop(self, reason: str) -> None:
        if self.is_stopped:
            return
        self._stop_reason = reason
        self._stopped.set()
        if self._stop_handler is not None:
            try:
                await self._stop_handler(reason)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 -- stop reporting boundary
                self._log("hubstudio_sample_stop_handler_failed")
        self._log("hubstudio_sample_listener_stopped")

    def _matches(self, *, hostname: str | None, path: str, method: str) -> bool:
        return (
            (hostname or "").casefold() in self._allowed_hosts
            and method.upper() == "POST"
            and path in self._allowed_paths
        )

    def _log(self, event: str, **values: object) -> None:
        target = self._preflight.target
        fields = validate_capture_log_fields(
            {
                "event": event,
                "tenant_id": str(target.tenant_id),
                "shop_id": str(target.shop_id),
                **values,
            }
        )
        fields.pop("event")
        _log(event, **fields)

    @staticmethod
    def _validate_paths(paths: frozenset[str]) -> None:
        if not paths or any(
            not path.startswith("/")
            or "*" in path
            or "?" in path
            or "#" in path
            or "://" in path
            for path in paths
        ):
            raise ValueError("Sample response whitelist requires exact URL paths.")

    @staticmethod
    def _validate_hosts(hosts: frozenset[str]) -> None:
        if not hosts or any(
            not host
            or "/" in host
            or "*" in host
            or ":" in host
            for host in hosts
        ):
            raise ValueError("Sample response whitelist requires exact hosts.")


async def _allowed_response_headers(response: Response) -> dict[str, str]:
    result: dict[str, str] = {}
    for name in ("content-type", *_REQUEST_ID_HEADERS):
        value = await response.header_value(name)
        if value is not None:
            result[name] = value
    return result


def _first_request_id(headers: dict[str, str]) -> str | None:
    value = next(
        (headers[name] for name in _REQUEST_ID_HEADERS if headers.get(name)), None
    )
    return _safe_request_id(value)


def _body_request_id(payload: object) -> str | None:
    if not isinstance(payload, Mapping):
        return None
    return _safe_request_id(payload.get("request_id"))


def _safe_request_id(value: object) -> str | None:
    return value if isinstance(value, str) and 0 < len(value) <= 200 else None


def _response_page_url(response: Response) -> str | None:
    try:
        value = response.request.frame.page.url
    except Exception:  # noqa: BLE001 -- service-worker responses have no frame
        return None
    return value if isinstance(value, str) else None


def _is_auth_page(page_url: str | None) -> bool:
    path = urlsplit(page_url or "").path.casefold()
    return any(marker in path for marker in _AUTH_PATH_MARKERS)


def _page_shop_ids(*urls: str | None) -> frozenset[str]:
    result: set[str] = set()
    for url in urls:
        query = parse_qs(urlsplit(url or "").query)
        for key in ("shop_id", "oec_seller_id"):
            result.update(value.strip() for value in query.get(key, []) if value.strip())
    return frozenset(result)


def _is_review_request_date(post_data: str | None) -> bool:
    try:
        payload = json.loads(post_data or "")
    except (TypeError, ValueError):
        return False
    search_params = payload.get("search_params", []) if isinstance(payload, Mapping) else None
    if not isinstance(payload, Mapping):
        return False
    order_params = payload.get("order_params")
    request_shape_matches = payload.get("tab") == 10 and order_params == []
    return (
        request_shape_matches
        and isinstance(search_params, list)
        and all(
            isinstance(item, Mapping) and item.get("value") in (None, "")
            for item in search_params
        )
    )
