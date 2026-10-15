from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select

from erp_api.infrastructure.database import Database
from erp_api.models.shop import Shop
from erp_api.models.shop_connection import ShopConnection
from erp_api.services.tiktok_client import TikTokShopIdentity, TikTokTokenSet
from erp_api.services.token_cipher import TokenCipher


class TikTokConnectionTargetChanged(RuntimeError):
    """The connection no longer belongs to the OAuth state target."""


class TikTokReauthorizationRepository:
    def __init__(self, database: Database, token_cipher: TokenCipher) -> None:
        self._database = database
        self._token_cipher = token_cipher

    async def replace_connection(
        self,
        tenant_id: UUID,
        shop_id: UUID,
        platform_shop_id: str,
        identity: TikTokShopIdentity,
        tokens: TikTokTokenSet,
        *,
        app_profile: str,
    ) -> Shop:
        if identity.platform_shop_id != platform_shop_id:
            raise TikTokConnectionTargetChanged(
                "The authorized TikTok shop does not match the OAuth target."
            )

        access_ciphertext = self._token_cipher.encrypt(tokens.access_token)
        refresh_ciphertext = (
            self._token_cipher.encrypt(tokens.refresh_token)
            if tokens.refresh_token
            else None
        )
        shop_ciphertext = (
            self._token_cipher.encrypt(identity.shop_cipher)
            if identity.shop_cipher
            else None
        )
        expires_at = (
            datetime.now(UTC) + timedelta(seconds=tokens.expires_in)
            if tokens.expires_in
            else None
        )

        async for session in self._database.session(tenant_id):
            result = await session.execute(
                select(Shop, ShopConnection)
                .join(ShopConnection, ShopConnection.shop_id == Shop.id)
                .where(Shop.id == shop_id, Shop.platform == "tiktok")
                .with_for_update(of=(Shop, ShopConnection))
            )
            row = result.one_or_none()
            if row is None or row[0].platform_shop_id != platform_shop_id:
                raise TikTokConnectionTargetChanged(
                    "The target TikTok shop connection changed."
                )

            shop, connection = row
            shop.shop_name = identity.name
            shop.region = identity.region
            shop.status = "active"
            connection.auth_status = "authorized"
            connection.app_profile = app_profile
            connection.access_token_ciphertext = access_ciphertext
            connection.refresh_token_ciphertext = refresh_ciphertext
            connection.shop_ciphertext = shop_ciphertext
            connection.expires_at = expires_at
            connection.scopes = list(tokens.scopes)
            connection.last_error = None
            await session.commit()
            return shop

        raise RuntimeError("Tenant database session was not created.")
