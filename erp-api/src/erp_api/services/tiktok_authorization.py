from __future__ import annotations

import json
import secrets
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlencode
from uuid import UUID

from redis.asyncio import Redis


@dataclass(frozen=True)
class TikTokAuthorizationState:
    user_id: UUID
    tenant_id: UUID
    intent: Literal["authorize", "scope_upgrade", "creator_authorize"]
    shop_id: UUID | None = None
    platform_shop_id: str | None = None
    required_scopes: tuple[str, ...] = ()
    app_profile: str = "legacy"


class TikTokAuthorizationService:
    def __init__(
        self,
        redis: Redis,
        *,
        service_id: str,
        authorization_url: str,
        app_key: str | None = None,
        creator_authorization_url: str | None = None,
        state_ttl_seconds: int = 600,
        app_profile: str = "legacy",
    ) -> None:
        self._redis = redis
        self._service_id = service_id
        self._authorization_url = authorization_url
        self._app_key = app_key
        self._creator_authorization_url = creator_authorization_url
        self._state_ttl_seconds = state_ttl_seconds
        self._app_profile = app_profile

    async def create_authorization_url(
        self,
        user_id: UUID,
        tenant_id: UUID,
        *,
        app_profile: str | None = None,
    ) -> str:
        self._require_profile(app_profile)
        return await self._create_authorization_url(
            TikTokAuthorizationState(
                user_id,
                tenant_id,
                "authorize",
                app_profile=self._app_profile,
            ),
            allow_missing_callback_state=True,
        )

    async def create_reauthorization_url(
        self,
        user_id: UUID,
        tenant_id: UUID,
        *,
        shop_id: UUID,
        platform_shop_id: str,
        required_scopes: Iterable[str],
        app_profile: str | None = None,
    ) -> str:
        self._require_profile(app_profile)
        scopes = tuple(sorted(set(required_scopes)))
        if not platform_shop_id or not scopes:
            raise ValueError("Scope upgrades require a target shop and scopes.")
        return await self._create_authorization_url(
            TikTokAuthorizationState(
                user_id,
                tenant_id,
                "scope_upgrade",
                shop_id=shop_id,
                platform_shop_id=platform_shop_id,
                required_scopes=scopes,
                app_profile=self._app_profile,
            ),
            allow_missing_callback_state=False,
        )

    async def create_creator_authorization_url(
        self,
        user_id: UUID,
        tenant_id: UUID,
        *,
        app_profile: str | None = None,
    ) -> str:
        self._require_profile(app_profile)
        if not self._app_key or not self._creator_authorization_url:
            raise ValueError("TikTok Creator authorization is not configured.")
        state = await self._store_state(
            TikTokAuthorizationState(
                user_id,
                tenant_id,
                "creator_authorize",
                app_profile=self._app_profile,
            )
        )
        separator = "&" if "?" in self._creator_authorization_url else "?"
        query = urlencode({"app_key": self._app_key, "state": state})
        return f"{self._creator_authorization_url}{separator}{query}"

    async def _create_authorization_url(
        self,
        context: TikTokAuthorizationState,
        *,
        allow_missing_callback_state: bool,
    ) -> str:
        state = await self._store_state(context)
        if allow_missing_callback_state:
            raw_record = await self._redis.get(self._state_key(state))
            if raw_record:
                await self._redis.set(
                    self._pending_key(), raw_record, ex=self._state_ttl_seconds
                )
        separator = "&" if "?" in self._authorization_url else "?"
        query = urlencode(
            {
                "service_id": self._service_id,
                "state": state,
            }
        )
        return f"{self._authorization_url}{separator}{query}"

    async def _store_state(self, context: TikTokAuthorizationState) -> str:
        state = secrets.token_urlsafe(32)
        record = json.dumps(
            {
                "userId": str(context.user_id),
                "tenantId": str(context.tenant_id),
                "state": state,
                "intent": context.intent,
                "shopId": str(context.shop_id) if context.shop_id else None,
                "platformShopId": context.platform_shop_id,
                "requiredScopes": list(context.required_scopes),
                "appProfile": context.app_profile,
            },
            separators=(",", ":"),
        )
        await self._redis.set(
            self._state_key(state),
            record,
            ex=self._state_ttl_seconds,
        )
        return state

    async def consume_state(self, state: str) -> TikTokAuthorizationState | None:
        raw_state = await self._redis.getdel(self._state_key(state))
        await self._clear_pending_state(state)
        return self._decode_state(raw_state)

    async def consume_callback_state(
        self,
        state: str | None,
        *,
        app_key: str | None = None,
    ) -> TikTokAuthorizationState | None:
        if app_key and self._app_key and app_key != self._app_key:
            return None
        if state:
            return await self.consume_state(state)
        raw_state = await self._redis.getdel(self._pending_key())
        if not raw_state:
            return None
        try:
            record = json.loads(raw_state)
            pending_state = record["state"]
        except (KeyError, TypeError, ValueError):
            return None
        await self._redis.getdel(self._state_key(pending_state))
        return self._decode_state(raw_state)

    async def _clear_pending_state(self, state: str) -> None:
        raw_pending = await self._redis.get(self._pending_key())
        if not raw_pending:
            return
        try:
            pending_state = json.loads(raw_pending)["state"]
        except (KeyError, TypeError, ValueError):
            return
        if pending_state == state:
            await self._redis.getdel(self._pending_key())

    @staticmethod
    def _decode_state(raw_state: str | None) -> TikTokAuthorizationState | None:
        if not raw_state:
            return None
        try:
            record = json.loads(raw_state)
            intent = record.get("intent", "authorize")
            if intent not in {"authorize", "scope_upgrade", "creator_authorize"}:
                return None
            shop_id = UUID(record["shopId"]) if record.get("shopId") else None
            platform_shop_id = record.get("platformShopId")
            required_scopes = tuple(sorted(set(record.get("requiredScopes") or [])))
            if intent == "scope_upgrade" and (
                shop_id is None or not platform_shop_id or not required_scopes
            ):
                return None
            return TikTokAuthorizationState(
                user_id=UUID(record["userId"]),
                tenant_id=UUID(record["tenantId"]),
                intent=intent,
                shop_id=shop_id,
                platform_shop_id=platform_shop_id,
                required_scopes=required_scopes,
                app_profile=record.get("appProfile") or "legacy",
            )
        except (KeyError, TypeError, ValueError):
            return None

    @staticmethod
    def _state_key(state: str) -> str:
        return f"tiktok:oauth-state:{state}"

    def _pending_key(self) -> str:
        return f"tiktok:oauth-pending:{self._service_id}"

    async def peek_state(self, state: str) -> TikTokAuthorizationState | None:
        return self._decode_state(await self._redis.get(self._state_key(state)))

    def _require_profile(self, app_profile: str | None) -> None:
        if app_profile is not None and app_profile != self._app_profile:
            raise ValueError("TikTok App profile is not configured.")
