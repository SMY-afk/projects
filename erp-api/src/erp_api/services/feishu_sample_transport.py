from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx

from erp_api.services.feishu_api_logging import log_api_call, request_started
from erp_api.services.feishu_sample_errors import FeishuSampleError

FEISHU_API_BASE_URL = "https://example.invalid/configure-resource"
FEISHU_RATE_LIMIT_CODE = 99991400
FEISHU_DATA_NOT_READY_CODE = 1254607
DEFAULT_FEISHU_RETRY_DELAYS = (1.0, 2.0, 4.0, 8.0)
MAX_FEISHU_RETRIES = 4
RetryMode = Literal["none", "idempotent", "rate_limit"]


@dataclass(frozen=True)
class FeishuResponseEvidence:
    request_id: str | None
    error_code: str | None
    http_status: int | None
    attempt: int


@dataclass
class FeishuRequestTrace:
    responses: list[FeishuResponseEvidence] = field(default_factory=list)

    @property
    def request_ids(self) -> list[str]:
        return list(
            dict.fromkeys(item.request_id for item in self.responses if item.request_id)
        )


class FeishuSampleTransport:
    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        http_transport: httpx.AsyncBaseTransport | None = None,
        retry_delays: tuple[float, ...] = DEFAULT_FEISHU_RETRY_DELAYS,
        sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
        business_type: str = "sample_management",
    ) -> None:
        if any(delay < 0 for delay in retry_delays):
            raise ValueError("Feishu retry delays cannot be negative.")
        if len(retry_delays) > MAX_FEISHU_RETRIES:
            raise ValueError("Feishu requests allow at most four retries.")
        if client is not None and http_transport is not None:
            raise ValueError("Feishu client and transport cannot both be supplied.")
        self._client = client
        self._http_transport = http_transport
        self._retry_delays = retry_delays
        self._sleeper = sleeper
        self._business_type = business_type
        self._trace: ContextVar[FeishuRequestTrace | None] = ContextVar(
            f"feishu_sample_trace_{id(self)}", default=None
        )

    @contextmanager
    def capture_evidence(self) -> Iterator[FeishuRequestTrace]:
        trace = FeishuRequestTrace()
        token = self._trace.set(trace)
        try:
            yield trace
        finally:
            self._trace.reset(token)

    async def request_json(
        self,
        method: str,
        path: str,
        *,
        retry_mode: RetryMode,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if self._client is not None:
            return await self._request_with_client(
                self._client, method, path, retry_mode=retry_mode, **kwargs
            )
        async with httpx.AsyncClient(
            base_url=FEISHU_API_BASE_URL,
            timeout=30,
            transport=self._http_transport,
        ) as client:
            return await self._request_with_client(
                client, method, path, retry_mode=retry_mode, **kwargs
            )

    async def _request_with_client(
        self,
        client: httpx.AsyncClient,
        method: str,
        path: str,
        *,
        retry_mode: RetryMode,
        **kwargs: Any,
    ) -> dict[str, Any]:
        for attempt in range(len(self._retry_delays) + 1):
            await self._before_request()
            request_time, started_at = request_started()
            try:
                response = await client.request(method, path, **kwargs)
            except httpx.HTTPError as exc:
                error_code = (
                    "timeout"
                    if isinstance(exc, httpx.TimeoutException)
                    else "transport_error"
                )
                log_api_call(
                    method,
                    path,
                    business_type=self._business_type,
                    request_time=request_time,
                    started_at=started_at,
                    status_code=None,
                    success=False,
                )
                self._record(None, error_code, None, attempt + 1)
                if not self._can_retry(retry_mode, "transport", attempt):
                    raise FeishuSampleError(
                        "Feishu request failed.", error_code=error_code
                    ) from None
            else:
                outcome = self._parse_response(response, attempt + 1)
                log_api_call(
                    method,
                    path,
                    business_type=self._business_type,
                    request_time=request_time,
                    started_at=started_at,
                    status_code=response.status_code,
                    success=isinstance(outcome, dict),
                )
                if isinstance(outcome, dict):
                    return outcome
                error, failure_kind = outcome
                if not self._can_retry(retry_mode, failure_kind, attempt):
                    raise error
            await self._sleeper(self._retry_delays[attempt])
        raise AssertionError("unreachable")

    async def _before_request(self) -> None:
        return None

    def _parse_response(
        self, response: httpx.Response, attempt: int
    ) -> dict[str, Any] | tuple[FeishuSampleError, str]:
        try:
            payload = response.json()
        except ValueError:
            payload = None
        request_id = _request_id(response, payload)
        if (
            isinstance(payload, dict)
            and payload.get("code") == 0
            and response.status_code < 400
        ):
            self._record(request_id, None, response.status_code, attempt)
            return payload
        code = payload.get("code") if isinstance(payload, dict) else None
        if isinstance(code, int) and not isinstance(code, bool) and code != 0:
            error_code = str(code)
        elif response.status_code >= 400:
            error_code = f"http_{response.status_code}"
        else:
            error_code = "invalid_response"
        self._record(request_id, error_code, response.status_code, attempt)
        error = FeishuSampleError(
            "Feishu request was rejected.",
            error_code=error_code,
            request_id=request_id,
        )
        if response.status_code == 429 or code == FEISHU_RATE_LIMIT_CODE:
            return error, "rate_limit"
        if response.status_code == 408:
            return error, "server"
        if code == FEISHU_DATA_NOT_READY_CODE:
            return error, "server"
        if response.status_code >= 500:
            return error, "server"
        return error, "business"

    def _can_retry(
        self, retry_mode: RetryMode, failure_kind: str, attempt: int
    ) -> bool:
        if attempt >= len(self._retry_delays):
            return False
        if failure_kind == "rate_limit":
            return retry_mode in {"idempotent", "rate_limit"}
        return retry_mode == "idempotent" and failure_kind in {
            "transport",
            "server",
        }

    def _record(
        self,
        request_id: str | None,
        error_code: str | None,
        http_status: int | None,
        attempt: int,
    ) -> None:
        trace = self._trace.get()
        if trace is not None:
            trace.responses.append(
                FeishuResponseEvidence(
                    request_id=request_id,
                    error_code=error_code,
                    http_status=http_status,
                    attempt=attempt,
                )
            )


def _request_id(response: httpx.Response, payload: object) -> str | None:
    candidates: list[object] = [response.headers.get("x-tt-logid")]
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            candidates.append(error.get("log_id"))
    for candidate in candidates:
        if (
            isinstance(candidate, str)
            and 1 <= len(candidate) <= 128
            and not any(character.isspace() for character in candidate)
        ):
            return candidate
    return None
