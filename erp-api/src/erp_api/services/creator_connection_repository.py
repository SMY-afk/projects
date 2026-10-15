from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from erp_api.infrastructure.database import Database
from erp_api.models.creator_connection import CreatorConnection
from erp_api.services.tiktok_schemas import TikTokTokenSet
from erp_api.services.token_cipher import TokenCipher

CREATOR_VIDEO_SCOPE = "creator.video.write"


class CreatorAuthorizationError(ValueError):
    pass


class CreatorConnectionRepository:
    def __init__(self, database: Database, token_cipher: TokenCipher) -> None:
        self._database = database
        self._token_cipher = token_cipher

    async def upsert_authorization(
        self,
        tenant_id: UUID,
        authorized_by_user_id: UUID,
        tokens: TikTokTokenSet,
    ) -> CreatorConnection:
        if tokens.user_type != 1:
            raise CreatorAuthorizationError("TikTok token subject is not a creator.")
        if not tokens.open_id:
            raise CreatorAuthorizationError("TikTok creator token has no open_id.")
        if CREATOR_VIDEO_SCOPE not in tokens.scopes:
            raise CreatorAuthorizationError(
                "TikTok creator did not grant creator.video.write."
            )
        now = datetime.now(UTC)
        expires_at = (
            now + timedelta(seconds=tokens.expires_in)
            if tokens.expires_in is not None
            else None
        )
        refresh_expires_at = (
            now + timedelta(seconds=tokens.refresh_expires_in)
            if tokens.refresh_expires_in is not None
            else None
        )
        async for session in self._database.session(tenant_id):
            connection_insert = insert(CreatorConnection).values(
                tenant_id=tenant_id,
                authorized_by_user_id=authorized_by_user_id,
                platform="tiktok",
                open_id=tokens.open_id,
                user_type=1,
                region=tokens.region,
                auth_status="authorized",
                access_token_ciphertext=self._token_cipher.encrypt(tokens.access_token),
                refresh_token_ciphertext=(
                    self._token_cipher.encrypt(tokens.refresh_token)
                    if tokens.refresh_token
                    else None
                ),
                expires_at=expires_at,
                refresh_expires_at=refresh_expires_at,
                scopes=sorted(set(tokens.scopes)),
                last_error=None,
            )
            connection_id = await session.scalar(
                connection_insert.on_conflict_do_update(
                    constraint="uq_creator_connections_tenant_platform_open_id",
                    set_={
                        "authorized_by_user_id": connection_insert.excluded.authorized_by_user_id,
                        "user_type": 1,
                        "region": connection_insert.excluded.region,
                        "auth_status": "authorized",
                        "access_token_ciphertext": connection_insert.excluded.access_token_ciphertext,
                        "refresh_token_ciphertext": connection_insert.excluded.refresh_token_ciphertext,
                        "expires_at": connection_insert.excluded.expires_at,
                        "refresh_expires_at": connection_insert.excluded.refresh_expires_at,
                        "scopes": connection_insert.excluded.scopes,
                        "last_error": None,
                        "updated_at": func.now(),
                    },
                ).returning(CreatorConnection.id)
            )
            if connection_id is None:
                raise RuntimeError("Creator connection upsert returned no identifier.")
            await session.commit()
            return CreatorConnection(
                id=connection_id,
                tenant_id=tenant_id,
                authorized_by_user_id=authorized_by_user_id,
                platform="tiktok",
                open_id=tokens.open_id,
                user_type=1,
                region=tokens.region,
                auth_status="authorized",
                access_token_ciphertext="<encrypted>",
                scopes=sorted(set(tokens.scopes)),
                expires_at=expires_at,
                refresh_expires_at=refresh_expires_at,
            )
        raise RuntimeError("Tenant database session was not created.")

    async def list_connections(self, tenant_id: UUID) -> list[dict[str, object]]:
        async for session in self._database.session(tenant_id):
            rows = await session.execute(
                select(CreatorConnection).order_by(
                    CreatorConnection.created_at, CreatorConnection.id
                )
            )
            return [
                {
                    "id": str(connection.id),
                    "openId": connection.open_id,
                    "region": connection.region,
                    "status": connection.auth_status,
                    "expiresAt": connection.expires_at,
                    "scopes": connection.scopes,
                }
                for connection in rows.scalars()
            ]
        return []
