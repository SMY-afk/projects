from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, func, select, update
from sqlalchemy.dialects.postgresql import insert

from erp_api.infrastructure.database import Database
from erp_api.models.shop import Shop
from erp_api.models.shop_connection import ShopConnection
from erp_api.services.tiktok_client import TikTokShopIdentity, TikTokTokenSet
from erp_api.services.token_cipher import TokenCipher


class ShopRepository:
    def __init__(self, database: Database, token_cipher: TokenCipher) -> None:
        self._database = database
        self._token_cipher = token_cipher

    async def list_shops(self, tenant_id: UUID) -> list[dict[str, object]]:
        async for session in self._database.session(tenant_id):
            rows = await session.execute(
                select(
                    Shop.id,
                    Shop.shop_name,
                    Shop.platform,
                    Shop.platform_shop_id,
                    Shop.timezone,
                )
                .where(Shop.status == "active")
                .order_by(Shop.shop_name, Shop.id)
            )
            return [
                {
                    "id": row.id,
                    "shopName": row.shop_name,
                    "platform": row.platform,
                    "platformShopId": row.platform_shop_id,
                    "timezone": row.timezone,
                }
                for row in rows
            ]
        return []

    async def upsert_tiktok_shop(
        self,
        tenant_id: UUID,
        identity: TikTokShopIdentity,
        tokens: TikTokTokenSet,
        *,
        app_profile: str = "legacy",
    ) -> Shop:
        async for session in self._database.session(tenant_id):
            shop_insert = insert(Shop).values(
                tenant_id=tenant_id,
                platform="tiktok",
                platform_shop_id=identity.platform_shop_id,
                shop_name=identity.name,
                region=identity.region,
                status="active",
            )
            shop_statement = shop_insert.on_conflict_do_update(
                constraint="uq_shops_tenant_platform_external_id",
                set_={
                    "shop_name": shop_insert.excluded.shop_name,
                    "region": shop_insert.excluded.region,
                    "status": "active",
                    "updated_at": func.now(),
                },
            ).returning(Shop.id)
            shop_id = await session.scalar(shop_statement)
            if shop_id is None:
                raise RuntimeError("TikTok shop upsert did not return an identifier.")
            expires_at = (
                datetime.now(UTC) + timedelta(seconds=tokens.expires_in)
                if tokens.expires_in
                else None
            )
            connection_insert = insert(ShopConnection).values(
                tenant_id=tenant_id,
                shop_id=shop_id,
                auth_status="authorized",
                app_profile=app_profile,
                access_token_ciphertext=self._token_cipher.encrypt(tokens.access_token),
                refresh_token_ciphertext=self._token_cipher.encrypt(
                    tokens.refresh_token
                )
                if tokens.refresh_token
                else None,
                shop_ciphertext=(
                    self._token_cipher.encrypt(identity.shop_cipher)
                    if identity.shop_cipher
                    else None
                ),
                expires_at=expires_at,
                scopes=tokens.scopes,
                last_error=None,
            )
            await session.execute(
                connection_insert.on_conflict_do_update(
                    constraint="uq_shop_connections_shop_id",
                    set_={
                        "auth_status": connection_insert.excluded.auth_status,
                        "app_profile": connection_insert.excluded.app_profile,
                        "access_token_ciphertext": connection_insert.excluded.access_token_ciphertext,
                        "refresh_token_ciphertext": connection_insert.excluded.refresh_token_ciphertext,
                        "shop_ciphertext": connection_insert.excluded.shop_ciphertext,
                        "expires_at": connection_insert.excluded.expires_at,
                        "scopes": connection_insert.excluded.scopes,
                        "last_error": None,
                    },
                )
            )
            await session.commit()
            return Shop(
                id=shop_id,
                platform="tiktok",
                platform_shop_id=identity.platform_shop_id,
                shop_name=identity.name,
            )
        raise RuntimeError("Tenant database session was not created.")

    async def get_connection_status(
        self, tenant_id: UUID, shop_id: UUID
    ) -> dict[str, object] | None:
        async for session in self._database.session(tenant_id):
            result = await session.execute(
                select(Shop, ShopConnection)
                .join(
                    ShopConnection,
                    and_(
                        ShopConnection.shop_id == Shop.id,
                        ShopConnection.tenant_id == Shop.tenant_id,
                    ),
                )
                .where(
                    Shop.tenant_id == tenant_id,
                    ShopConnection.tenant_id == tenant_id,
                    Shop.id == shop_id,
                    Shop.platform == "tiktok",
                )
            )
            row = result.one_or_none()
            if not row:
                return None
            shop, connection = row
            return {
                "shopId": str(shop.id),
                "platformShopId": shop.platform_shop_id,
                "shopName": shop.shop_name,
                "region": shop.region,
                "timezone": shop.timezone,
                "status": connection.auth_status,
                "appProfile": connection.app_profile,
                "expiresAt": connection.expires_at,
                "updatedAt": connection.updated_at,
                "scopes": connection.scopes,
            }
        return None

    async def get_refresh_token(self, tenant_id: UUID, shop_id: UUID) -> str | None:
        async for session in self._database.session(tenant_id):
            ciphertext = await session.scalar(
                select(ShopConnection.refresh_token_ciphertext)
                .join(Shop, Shop.id == ShopConnection.shop_id)
                .where(
                    Shop.id == shop_id,
                    Shop.platform == "tiktok",
                    ShopConnection.auth_status == "authorized",
                )
            )
            return self._token_cipher.decrypt(ciphertext) if ciphertext else None
        return None

    async def get_app_profile(self, tenant_id: UUID, shop_id: UUID) -> str | None:
        async for session in self._database.session(tenant_id):
            return await session.scalar(
                select(ShopConnection.app_profile)
                .join(Shop, Shop.id == ShopConnection.shop_id)
                .where(
                    Shop.id == shop_id,
                    Shop.tenant_id == tenant_id,
                    Shop.platform == "tiktok",
                )
            )
        return None

    async def get_shop_cipher(self, tenant_id: UUID, shop_id: UUID) -> str | None:
        async for session in self._database.session(tenant_id):
            ciphertext = await session.scalar(
                select(ShopConnection.shop_ciphertext)
                .join(Shop, Shop.id == ShopConnection.shop_id)
                .where(
                    Shop.id == shop_id,
                    Shop.platform == "tiktok",
                    ShopConnection.auth_status == "authorized",
                )
            )
            return self._token_cipher.decrypt(ciphertext) if ciphertext else None
        return None

    async def get_access_token(self, tenant_id: UUID, shop_id: UUID) -> str | None:
        async for session in self._database.session(tenant_id):
            ciphertext = await session.scalar(
                select(ShopConnection.access_token_ciphertext)
                .join(Shop, Shop.id == ShopConnection.shop_id)
                .where(
                    Shop.id == shop_id,
                    Shop.platform == "tiktok",
                    ShopConnection.auth_status == "authorized",
                )
            )
            return self._token_cipher.decrypt(ciphertext) if ciphertext else None
        return None

    async def get_connection_tokens(
        self, tenant_id: UUID, shop_id: UUID
    ) -> tuple[str | None, datetime | None, str | None] | None:
        async for session in self._database.session(tenant_id):
            row = (
                await session.execute(
                    select(
                        ShopConnection.refresh_token_ciphertext,
                        ShopConnection.expires_at,
                        ShopConnection.shop_ciphertext,
                    ).where(
                        ShopConnection.shop_id == shop_id,
                        ShopConnection.auth_status == "authorized",
                    )
                )
            ).one_or_none()
            if row is None:
                return None
            return (
                self._token_cipher.decrypt(row[0]) if row[0] else None,
                row[1],
                self._token_cipher.decrypt(row[2]) if row[2] else None,
            )
        return None

    async def get_authorized_tiktok_shop(
        self, tenant_id: UUID, shop_id: UUID | None = None
    ) -> dict[str, object] | None:
        async for session in self._database.session(tenant_id):
            result = await session.execute(
                select(
                    Shop.id,
                    Shop.platform_shop_id,
                    Shop.shop_name,
                    Shop.region,
                    Shop.timezone,
                )
                .join(ShopConnection, ShopConnection.shop_id == Shop.id)
                .where(
                    Shop.platform == "tiktok",
                    ShopConnection.auth_status == "authorized",
                    *([Shop.id == shop_id] if shop_id is not None else []),
                )
                .order_by(Shop.created_at.desc())
                .limit(1)
            )
            row = result.one_or_none()
            if row is None:
                return None
            return {
                "id": row[0],
                "platform_shop_id": row[1],
                "name": row[2],
                "region": row[3],
                "timezone": row[4],
            }
        return None

    async def update_connection_tokens(
        self, tenant_id: UUID, shop_id: UUID, tokens: TikTokTokenSet
    ) -> bool:
        expires_at = (
            datetime.now(UTC) + timedelta(seconds=tokens.expires_in)
            if tokens.expires_in
            else None
        )
        async for session in self._database.session(tenant_id):
            statement = (
                update(ShopConnection)
                .where(
                    ShopConnection.shop_id == shop_id,
                    ShopConnection.auth_status == "authorized",
                )
                .values(
                    access_token_ciphertext=self._token_cipher.encrypt(
                        tokens.access_token
                    ),
                    refresh_token_ciphertext=(
                        self._token_cipher.encrypt(tokens.refresh_token)
                        if tokens.refresh_token
                        else ShopConnection.refresh_token_ciphertext
                    ),
                    expires_at=expires_at,
                    scopes=tokens.scopes,
                    last_error=None,
                )
            )
            result = await session.execute(statement)
            await session.commit()
            return result.rowcount == 1
        return False

    async def disconnect(self, tenant_id: UUID, shop_id: UUID) -> bool:
        async for session in self._database.session(tenant_id):
            result = await session.execute(
                update(ShopConnection)
                .where(ShopConnection.shop_id == shop_id)
                .values(
                    auth_status="disconnected",
                    access_token_ciphertext=None,
                    refresh_token_ciphertext=None,
                    expires_at=None,
                    scopes=[],
                    last_error=None,
                )
            )
            await session.commit()
            return result.rowcount == 1
        return False
