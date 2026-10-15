from __future__ import annotations

from datetime import UTC, datetime, timedelta

from erp_api.services.platform_fulfillment_adapter import (
    PlatformFulfillmentCommand,
    PlatformFulfillmentError,
    PlatformFulfillmentResult,
)
from erp_api.services.tiktok_fulfillment_client import TikTokFulfillmentClient
from erp_api.services.tiktok_transport import TikTokApiError, tiktok_request_context

_ALREADY_FULFILLED_CODES = frozenset(
    {"11006021", "21008099", "21011020", "21011027", "21011040"}
)


class TikTokFulfillmentAdapter:
    platform = "tiktok"

    def __init__(
        self, shop_repository, token_client, fulfillment_client: TikTokFulfillmentClient
    ) -> None:
        self._shop_repository = shop_repository
        self._token_client = token_client
        self._fulfillment_client = fulfillment_client

    async def fulfill(
        self, command: PlatformFulfillmentCommand
    ) -> PlatformFulfillmentResult:
        platform, package_id, tracking_number, carrier_id = _validate(command)
        if platform != self.platform:
            raise PlatformFulfillmentError(
                "TikTok adapter received a command for another platform.",
                code="platform_adapter_mismatch",
                retryable=False,
            )
        with tiktok_request_context(
            tenant_id=str(command.tenant_id), shop_id=str(command.shop_id)
        ):
            access_token, shop_cipher = await self._credentials(command)
            try:
                request_id = await self._fulfillment_client.ship_package(
                    access_token,
                    shop_cipher=shop_cipher,
                    platform_package_id=package_id,
                    tracking_number=tracking_number,
                    shipping_provider_id=carrier_id,
                )
            except TikTokApiError as error:
                if error.code not in _ALREADY_FULFILLED_CODES:
                    raise
                request_id = error.request_id
        return PlatformFulfillmentResult(platform_request_id=request_id)

    async def _credentials(
        self, command: PlatformFulfillmentCommand
    ) -> tuple[str, str]:
        access_token = await self._shop_repository.get_access_token(
            command.tenant_id, command.shop_id
        )
        connection = await self._shop_repository.get_connection_tokens(
            command.tenant_id, command.shop_id
        )
        if not connection or not connection[2]:
            raise PlatformFulfillmentError(
                "TikTok connection credentials are unavailable.",
                code="platform_credentials_unavailable",
                retryable=False,
            )
        refresh_token, expires_at, shop_cipher = connection
        needs_refresh = not access_token or (
            expires_at is not None
            and expires_at <= datetime.now(UTC) + timedelta(seconds=60)
        )
        if needs_refresh:
            if not refresh_token:
                code = (
                    "platform_credentials_unavailable"
                    if not access_token
                    else "platform_token_expired"
                )
                raise PlatformFulfillmentError(
                    "TikTok access token cannot be refreshed.",
                    code=code,
                    retryable=False,
                )
            tokens = await self._token_client.refresh_access_token(refresh_token)
            updated = await self._shop_repository.update_connection_tokens(
                command.tenant_id, command.shop_id, tokens
            )
            if not updated:
                raise PlatformFulfillmentError(
                    "TikTok connection token refresh could not be persisted.",
                    code="platform_token_refresh_failed",
                    retryable=True,
                )
            access_token = tokens.access_token
        return access_token, shop_cipher


def _validate(command: PlatformFulfillmentCommand) -> tuple[str, str, str, str]:
    platform = command.platform.strip().lower()
    package_id = (command.platform_package_id or "").strip()
    tracking_number = command.tracking_number.strip()
    carrier_id = (command.platform_carrier_id or "").strip()
    if not package_id:
        raise PlatformFulfillmentError(
            "TikTok platform package mapping is required.",
            code="platform_package_mapping_required",
            retryable=False,
        )
    if not tracking_number:
        raise PlatformFulfillmentError(
            "TikTok tracking number is required.",
            code="tracking_number_required",
            retryable=False,
        )
    if not carrier_id:
        raise PlatformFulfillmentError(
            "TikTok platform carrier mapping is required.",
            code="platform_carrier_mapping_required",
            retryable=False,
        )
    return platform, package_id, tracking_number, carrier_id
