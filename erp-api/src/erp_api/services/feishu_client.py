from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any
from weakref import WeakKeyDictionary

import httpx

from erp_api.core.config import get_settings
from erp_api.services.feishu_rate_limiter import (
    FeishuRateLimiter,
    shared_feishu_rate_limiter,
)
from erp_api.services.feishu_sample_errors import FeishuSampleError
from erp_api.services.feishu_sample_transport import (
    DEFAULT_FEISHU_RETRY_DELAYS,
    FeishuSampleTransport,
    RetryMode,
)

TOKEN_REFRESH_SKEW_SECONDS = 300.0
_TOKEN_PATH = "/open-apis/auth/v3/tenant_access_token/internal"


@dataclass
class _TokenState:
    token: str | None = None
    refresh_at: float = 0.0
    expires_at: float = 0.0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


_shared_tokens: WeakKeyDictionary[
    asyncio.AbstractEventLoop, dict[tuple[str, str], _TokenState]
] = WeakKeyDictionary()


class FeishuClient(FeishuSampleTransport):
    """Single entrypoint for Feishu requests and per-process tenant token caching."""

    def __init__(
        self,
        *,
        app_id: str | None = None,
        app_secret: str | None = None,
        token_provider: Callable[[], Awaitable[str]] | None = None,
        client: httpx.AsyncClient | None = None,
        http_transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
        token_refresh_skew_seconds: float = TOKEN_REFRESH_SKEW_SECONDS,
        retry_delays: tuple[float, ...] = DEFAULT_FEISHU_RETRY_DELAYS,
        sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
        business_type: str = "sample_management",
        rate_limiter: FeishuRateLimiter | None = None,
    ) -> None:
        if token_provider is None and (not app_id or not app_secret):
            raise ValueError("Feishu app credentials are required.")
        if token_provider is not None and (
            app_id is not None or app_secret is not None
        ):
            raise ValueError("Feishu token provider and credentials are exclusive.")
        super().__init__(
            client=client,
            http_transport=http_transport,
            retry_delays=retry_delays,
            sleeper=sleeper,
            business_type=business_type,
        )
        self._app_id = app_id
        self._app_secret = app_secret
        self._token_provider = token_provider
        self._clock = clock
        self._token_refresh_skew_seconds = token_refresh_skew_seconds
        self._rate_limiter = rate_limiter
        self._private_token = (
            _TokenState() if client is not None or http_transport is not None else None
        )

    async def _before_request(self) -> None:
        limiter = self._rate_limiter
        if limiter is None:
            redis_url = os.getenv("REDIS_URL") or get_settings().redis_url
            limiter = shared_feishu_rate_limiter(redis_url)
        await limiter.acquire()

    async def tenant_access_token(self) -> str:
        if self._token_provider is not None:
            return await self._token_provider()
        state = self._token_state()
        if state.token and self._clock() < state.refresh_at:
            return state.token
        async with state.lock:
            if state.token and self._clock() < state.refresh_at:
                return state.token
            try:
                payload = await self.request_json(
                    "POST",
                    _TOKEN_PATH,
                    json={"app_id": self._app_id, "app_secret": self._app_secret},
                    retry_mode="idempotent",
                )
                token = payload.get("tenant_access_token")
                if not isinstance(token, str) or not token:
                    raise FeishuSampleError("Feishu token response is missing a token.")
                expires_in = payload.get("expire")
                if (
                    isinstance(expires_in, bool)
                    or not isinstance(expires_in, int)
                    or expires_in <= 0
                ):
                    raise FeishuSampleError("Feishu token response has invalid expiry.")
            except FeishuSampleError:
                now = self._clock()
                if state.token and now < state.expires_at:
                    state.refresh_at = min(state.expires_at, now + 30)
                    return state.token
                raise
            skew = min(self._token_refresh_skew_seconds, expires_in / 2)
            state.token = token
            state.expires_at = self._clock() + expires_in
            state.refresh_at = state.expires_at - skew
            return token

    def _token_state(self) -> _TokenState:
        if self._private_token is not None:
            return self._private_token
        loop = asyncio.get_running_loop()
        by_app = _shared_tokens.setdefault(loop, {})
        assert self._app_id is not None and self._app_secret is not None
        return by_app.setdefault((self._app_id, self._app_secret), _TokenState())

    async def list_records(
        self, app_token: str, table_id: str, *, params: dict[str, object]
    ) -> dict[str, Any]:
        return await self._bitable_records(
            "GET", app_token, table_id, params=params, retry_mode="idempotent"
        )

    async def get_record(
        self, app_token: str, table_id: str, record_id: str
    ) -> dict[str, Any]:
        return await self._bitable_records(
            "GET",
            app_token,
            table_id,
            record_id=record_id,
            retry_mode="idempotent",
        )

    async def create_record(
        self, app_token: str, table_id: str, fields: dict[str, Any]
    ) -> dict[str, Any]:
        return await self._bitable_records(
            "POST",
            app_token,
            table_id,
            json={"fields": fields},
            retry_mode="rate_limit",
        )

    async def update_record(
        self, app_token: str, table_id: str, record_id: str, fields: dict[str, Any]
    ) -> dict[str, Any]:
        return await self._bitable_records(
            "PUT",
            app_token,
            table_id,
            record_id=record_id,
            json={"fields": fields},
            retry_mode="idempotent",
        )

    async def batch_records(
        self,
        app_token: str,
        table_id: str,
        action: str,
        records: list[dict[str, object]] | list[str],
        *,
        retry_mode: RetryMode,
    ) -> dict[str, Any]:
        if action not in {"batch_create", "batch_update", "batch_delete"}:
            raise ValueError("Unsupported Feishu batch action.")
        return await self._bitable_records(
            "POST",
            app_token,
            table_id,
            action=action,
            json={"records": records},
            retry_mode=retry_mode,
        )

    async def send_card(
        self,
        *,
        receive_id: str,
        receive_id_type: str,
        content: str,
        idempotency_key: str,
    ) -> str:
        token = await self.tenant_access_token()
        payload = await self.request_json(
            "POST",
            "/open-apis/im/v1/messages",
            retry_mode="idempotent",
            headers={"Authorization": f"Bearer {token}"},
            params={"receive_id_type": receive_id_type},
            json={
                "receive_id": receive_id,
                "msg_type": "interactive",
                "content": content,
                "uuid": idempotency_key,
            },
        )
        data = payload.get("data")
        message_id = data.get("message_id") if isinstance(data, dict) else None
        if not isinstance(message_id, str) or not message_id:
            raise FeishuSampleError(
                "Feishu notification response is missing message_id.",
                error_code="invalid_response",
            )
        return message_id

    async def _bitable_records(
        self,
        method: str,
        app_token: str,
        table_id: str,
        *,
        retry_mode: RetryMode,
        record_id: str | None = None,
        action: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        path = f"/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"
        if record_id:
            path += f"/{record_id}"
        if action:
            path += f"/{action}"
        token = await self.tenant_access_token()
        payload = await self.request_json(
            method,
            path,
            retry_mode=retry_mode,
            headers={"Authorization": f"Bearer {token}"},
            **kwargs,
        )
        data = payload.get("data")
        return data if isinstance(data, dict) else {}
