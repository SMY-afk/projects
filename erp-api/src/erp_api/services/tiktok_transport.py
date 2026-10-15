from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from typing import Any, Literal

import httpx

HTTPMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
Sleep = Callable[[float], Awaitable[None]]
logger = logging.getLogger("erp_api.tiktok")


@dataclass(frozen=True)
class TikTokRequestContext:
    tenant_id: str | None = None
    shop_id: str | None = None
    app_profile: str | None = None


_request_context: ContextVar[TikTokRequestContext | None] = ContextVar(
    "tiktok_request_context", default=None
)


@contextmanager
def tiktok_request_context(
    *,
    tenant_id: str | None = None,
    shop_id: str | None = None,
    app_profile: str | None = None,
) -> Iterator[None]:
    token = _request_context.set(
        TikTokRequestContext(
            tenant_id=tenant_id,
            shop_id=shop_id,
            app_profile=app_profile,
        )
    )
    try:
        yield
    finally:
        _request_context.reset(token)


def get_tiktok_request_context() -> TikTokRequestContext:
    return _request_context.get() or TikTokRequestContext()


class TikTokClientError(RuntimeError):
    """Base error for requests to TikTok Shop."""


class TikTokApiError(TikTokClientError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "platform_api_error",
        status_code: int = 502,
        request_id: str | None = None,
        upstream_status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.request_id = request_id
        self.upstream_status_code = upstream_status_code


class TikTokRateLimitError(TikTokApiError):
    def __init__(
        self, *, retry_after_seconds: float | None, request_id: str | None = None
    ) -> None:
        super().__init__(
            "TikTok request was rate limited.",
            code="rate_limited",
            status_code=429,
            request_id=request_id,
        )
        self.retry_after_seconds = retry_after_seconds


class TikTokTimeoutError(TikTokClientError):
    pass


@dataclass(frozen=True)
class TikTokRequest:
    method: HTTPMethod
    path: str
    query: dict[str, str] = field(default_factory=dict)
    json_body: dict[str, Any] | None = None
    form: dict[str, str] | None = None
    signed: bool = True
    credentials_in_query: bool = False
    retryable: bool | None = None


@dataclass(frozen=True)
class TikTokResponse:
    payload: dict[str, Any]
    platform_request_id: str | None
    status_code: int


class TikTokTransport:
    RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})

    def __init__(
        self,
        *,
        base_url: str,
        app_key: str,
        app_secret: str,
        timeout_seconds: float = 10.0,
        max_retries: int = 2,
        retry_base_seconds: float = 0.5,
        max_retry_delay_seconds: float = 30.0,
        http_transport: httpx.AsyncBaseTransport | None = None,
        sleep: Sleep = asyncio.sleep,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._app_key = app_key
        self._app_secret = app_secret
        self._timeout = httpx.Timeout(timeout_seconds)
        self._max_retries = max_retries
        self._retry_base_seconds = retry_base_seconds
        self._max_retry_delay_seconds = max_retry_delay_seconds
        self._http_transport = http_transport
        self._sleep = sleep
        self._clock = clock

    async def request(
        self,
        request: TikTokRequest,
        *,
        access_token: str | None = None,
        tenant_id: str | None = None,
        shop_id: str | None = None,
    ) -> dict[str, Any]:
        response = await self.request_with_metadata(
            request,
            access_token=access_token,
            tenant_id=tenant_id,
            shop_id=shop_id,
        )
        return response.payload

    async def request_with_metadata(
        self,
        request: TikTokRequest,
        *,
        access_token: str | None = None,
        tenant_id: str | None = None,
        shop_id: str | None = None,
    ) -> TikTokResponse:
        method = request.method.upper()
        path = request.path if request.path.startswith("/") else f"/{request.path}"
        query = dict(request.query)
        form = dict(request.form or {})
        if request.credentials_in_query:
            query.update({"app_key": self._app_key, "app_secret": self._app_secret})
        body_bytes = self._body_bytes(request)
        if request.signed:
            query.update(
                {"app_key": self._app_key, "timestamp": str(int(self._clock()))}
            )
            query["sign"] = self._sign(path, query, body_bytes)
        headers = {"Accept": "application/json", "User-Agent": "erp-api/0.1"}
        if request.json_body is not None:
            headers["Content-Type"] = "application/json"
        if access_token:
            headers["X-Tts-Access-Token"] = access_token
        retryable = (
            request.retryable
            if request.retryable is not None
            else method in {"GET", "DELETE"}
        )

        started_at = time.perf_counter()
        attempts = 0
        try:
            for attempt in range(self._max_retries + 1):
                attempts = attempt + 1
                try:
                    async with httpx.AsyncClient(
                        timeout=self._timeout, transport=self._http_transport
                    ) as client:
                        response = await client.request(
                            method,
                            f"{self._base_url}{path}",
                            params=query,
                            content=body_bytes or None,
                            data=form or None,
                            headers=headers,
                        )
                except httpx.TimeoutException as error:
                    if retryable and attempt < self._max_retries:
                        await self._sleep(self._backoff(attempt))
                        continue
                    raise TikTokTimeoutError("TikTok request timed out.") from error
                except httpx.HTTPError as error:
                    if retryable and attempt < self._max_retries:
                        await self._sleep(self._backoff(attempt))
                        continue
                    raise TikTokClientError("TikTok request failed.") from error

                retry_after = self._retry_after(response)
                if (
                    response.status_code in self.RETRYABLE_STATUS_CODES
                    and retryable
                    and attempt < self._max_retries
                ):
                    await self._sleep(
                        retry_after
                        if retry_after is not None
                        else self._backoff(attempt)
                    )
                    continue
                result = self._parse_response(response, retry_after)
                platform_request_id = self._platform_request_id(response, result)
                self._log_request(
                    result="success",
                    attempts=attempts,
                    duration_ms=self._duration_ms(started_at),
                    platform_request_id=platform_request_id,
                    tenant_id=tenant_id,
                    shop_id=shop_id,
                )
                return TikTokResponse(
                    payload=result,
                    platform_request_id=platform_request_id,
                    status_code=response.status_code,
                )
        except TikTokClientError as error:
            self._log_request(
                result="error",
                attempts=attempts,
                duration_ms=self._duration_ms(started_at),
                platform_request_id=getattr(error, "request_id", None),
                error_code=self._safe_error_code(error),
                tenant_id=tenant_id,
                shop_id=shop_id,
            )
            raise

        raise TikTokClientError("TikTok request failed after retries.")

    @staticmethod
    def _duration_ms(started_at: float) -> float:
        return round((time.perf_counter() - started_at) * 1000, 2)

    @staticmethod
    def _platform_request_id(
        response: httpx.Response, payload: dict[str, Any] | None = None
    ) -> str | None:
        header_value = response.headers.get("x-tts-request-id") or response.headers.get(
            "x-request-id"
        )
        if header_value:
            return header_value
        body_value = payload.get("request_id") if payload is not None else None
        return body_value if isinstance(body_value, str) and body_value else None

    @staticmethod
    def _safe_error_code(error: TikTokClientError) -> str:
        if isinstance(error, TikTokRateLimitError):
            return "rate_limited"
        if isinstance(error, TikTokApiError):
            return {
                "36004004": "invalid_auth_code",
                "36009004": "invalid_app_credentials",
                "105005": "access_denied",
            }.get(error.code, "platform_api_error")
        if isinstance(error, TikTokTimeoutError):
            return "timeout"
        return "transport_error"

    def _log_request(
        self,
        *,
        result: str,
        attempts: int,
        duration_ms: float,
        platform_request_id: str | None,
        tenant_id: str | None,
        shop_id: str | None,
        error_code: str | None = None,
    ) -> None:
        context = get_tiktok_request_context()
        extra: dict[str, object] = {
            "event": "tiktok_request_completed",
            "tenant_id": tenant_id or context.tenant_id,
            "shop_id": shop_id or context.shop_id,
            "platform_request_id": platform_request_id,
            "duration_ms": duration_ms,
            "result": result,
            "attempts": attempts,
        }
        if error_code:
            extra["error_code"] = error_code
        logger.error(
            "tiktok_request_failed", extra=extra
        ) if result == "error" else logger.info("tiktok_request_completed", extra=extra)

    def _sign(self, path: str, query: dict[str, str], body: bytes) -> str:
        parameters = "".join(
            f"{key}{query[key]}"
            for key in sorted(query)
            if key not in {"access_token", "sign"}
        )
        signing_value = (
            self._app_secret.encode()
            + path.encode()
            + parameters.encode()
            + body
            + self._app_secret.encode()
        )
        return hmac.new(
            self._app_secret.encode(), signing_value, hashlib.sha256
        ).hexdigest()

    @staticmethod
    def _body_bytes(request: TikTokRequest) -> bytes:
        if request.json_body is not None:
            return json.dumps(
                request.json_body,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
        return b""

    def _backoff(self, attempt: int) -> float:
        return min(
            self._retry_base_seconds * (2**attempt), self._max_retry_delay_seconds
        )

    def _retry_after(self, response: httpx.Response) -> float | None:
        value = response.headers.get("Retry-After")
        if not value:
            return None
        try:
            delay = float(value)
        except ValueError:
            try:
                delay = parsedate_to_datetime(value).timestamp() - self._clock()
            except (TypeError, ValueError, OverflowError):
                return None
        return min(max(delay, 0.0), self._max_retry_delay_seconds)

    @staticmethod
    def _parse_response(
        response: httpx.Response, retry_after: float | None
    ) -> dict[str, Any]:
        request_id = TikTokTransport._platform_request_id(response)
        if response.status_code == 429:
            raise TikTokRateLimitError(
                retry_after_seconds=retry_after, request_id=request_id
            )
        try:
            payload = response.json()
        except ValueError as error:
            raise TikTokApiError(
                "TikTok returned an invalid response.",
                code="invalid_response",
                status_code=502,
                request_id=request_id,
            ) from error
        if not isinstance(payload, dict):
            raise TikTokApiError(
                "TikTok returned an invalid response.",
                code="invalid_response",
                status_code=502,
            )
        request_id = TikTokTransport._platform_request_id(response, payload)
        platform_code = payload.get("code")
        has_platform_error = platform_code not in (None, 0, "0", "success", "SUCCESS")
        if response.is_error or has_platform_error:
            code = str(platform_code or f"http_{response.status_code}")
            raise TikTokApiError(
                "TikTok API rejected the request.",
                code=code,
                status_code=502,
                request_id=request_id,
                upstream_status_code=response.status_code,
            )
        return payload
