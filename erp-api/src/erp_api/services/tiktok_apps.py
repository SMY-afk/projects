from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from erp_api.services.shop_repository import ShopRepository
from erp_api.services.tiktok_authorization import (
    TikTokAuthorizationService,
    TikTokAuthorizationState,
)
from erp_api.services.tiktok_transport import (
    TikTokClientError,
    TikTokRequest,
    TikTokResponse,
    TikTokTransport,
    get_tiktok_request_context,
)

LEGACY_TIKTOK_APP_PROFILE = "legacy"


@dataclass(frozen=True)
class TikTokAppProfile:
    name: str
    app_key: str
    app_secret: str
    service_id: str


class TikTokAppRegistry:
    def __init__(
        self,
        profiles: Mapping[str, TikTokAppProfile],
        shop_repository: ShopRepository,
        *,
        timeout_seconds: float,
        max_retries: int,
        retry_base_seconds: float,
        max_retry_delay_seconds: float,
    ) -> None:
        if LEGACY_TIKTOK_APP_PROFILE not in profiles:
            raise ValueError("The legacy TikTok App profile must be configured.")
        self._profiles = dict(profiles)
        self._shop_repository = shop_repository
        self._transport_options = {
            "timeout_seconds": timeout_seconds,
            "max_retries": max_retries,
            "retry_base_seconds": retry_base_seconds,
            "max_retry_delay_seconds": max_retry_delay_seconds,
        }

    @property
    def profiles(self) -> Mapping[str, TikTokAppProfile]:
        return self._profiles

    def require_profile(self, name: str) -> TikTokAppProfile:
        profile = self._profiles.get(name)
        if profile is None:
            raise ValueError("TikTok App profile is not configured.")
        return profile

    def profile_for_app_key(self, app_key: str) -> str | None:
        return next(
            (
                name
                for name, profile in self._profiles.items()
                if profile.app_key == app_key
            ),
            None,
        )

    async def resolve_profile(self, tenant_id: str, shop_id: str) -> str:
        try:
            profile = await self._shop_repository.get_app_profile(
                UUID(tenant_id), UUID(shop_id)
            )
        except ValueError as error:
            raise TikTokClientError("Invalid TikTok request context.") from error
        if profile is None:
            raise TikTokClientError("TikTok shop connection was not found.")
        self.require_profile(profile)
        return profile

    def create_transport(self, base_url: str) -> TikTokAppTransport:
        transports = {
            name: TikTokTransport(
                base_url=base_url,
                app_key=profile.app_key,
                app_secret=profile.app_secret,
                **self._transport_options,
            )
            for name, profile in self._profiles.items()
        }
        return TikTokAppTransport(transports, self)


class TikTokAppTransport:
    def __init__(
        self,
        transports: Mapping[str, TikTokTransport],
        registry: TikTokAppRegistry,
    ) -> None:
        self._transports = dict(transports)
        self._registry = registry

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
        context = get_tiktok_request_context()
        selected_tenant_id = tenant_id or context.tenant_id
        selected_shop_id = shop_id or context.shop_id
        profile_name = context.app_profile
        if profile_name is None and selected_tenant_id and selected_shop_id:
            profile_name = await self._registry.resolve_profile(
                selected_tenant_id, selected_shop_id
            )
        profile_name = profile_name or LEGACY_TIKTOK_APP_PROFILE
        transport = self._transports.get(profile_name)
        if transport is None:
            raise TikTokClientError("TikTok App profile is not configured.")
        return await transport.request_with_metadata(
            request,
            access_token=access_token,
            tenant_id=selected_tenant_id,
            shop_id=selected_shop_id,
        )


class TikTokMultiAppAuthorizationService:
    def __init__(
        self,
        services: Mapping[str, TikTokAuthorizationService],
        registry: TikTokAppRegistry,
    ) -> None:
        self._services = dict(services)
        self._registry = registry

    def _service(self, app_profile: str | None) -> TikTokAuthorizationService:
        name = app_profile or LEGACY_TIKTOK_APP_PROFILE
        service = self._services.get(name)
        if service is None:
            raise ValueError("TikTok App profile is not configured.")
        return service

    async def create_authorization_url(
        self, user_id: UUID, tenant_id: UUID, *, app_profile: str | None = None
    ) -> str:
        return await self._service(app_profile).create_authorization_url(
            user_id, tenant_id, app_profile=app_profile
        )

    async def create_reauthorization_url(
        self,
        user_id: UUID,
        tenant_id: UUID,
        *,
        shop_id: UUID,
        platform_shop_id: str,
        required_scopes: tuple[str, ...] | list[str],
        app_profile: str | None = None,
    ) -> str:
        return await self._service(app_profile).create_reauthorization_url(
            user_id,
            tenant_id,
            shop_id=shop_id,
            platform_shop_id=platform_shop_id,
            required_scopes=required_scopes,
            app_profile=app_profile,
        )

    async def create_creator_authorization_url(
        self, user_id: UUID, tenant_id: UUID
    ) -> str:
        return await self._service(None).create_creator_authorization_url(
            user_id, tenant_id
        )

    async def consume_callback_state(
        self, state: str | None, *, app_key: str | None = None
    ) -> TikTokAuthorizationState | None:
        if state:
            context = await self._service(None).peek_state(state)
            if context is None:
                return None
            return await self._service(context.app_profile).consume_callback_state(
                state, app_key=app_key
            )
        profile_name = (
            self._registry.profile_for_app_key(app_key)
            if app_key
            else LEGACY_TIKTOK_APP_PROFILE
        )
        if profile_name is None:
            return None
        return await self._service(profile_name).consume_callback_state(
            None, app_key=app_key
        )
