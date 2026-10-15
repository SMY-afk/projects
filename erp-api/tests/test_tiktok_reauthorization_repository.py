from __future__ import annotations

import asyncio
from uuid import UUID

import pytest

from erp_api.models.shop import Shop
from erp_api.models.shop_connection import ShopConnection
from erp_api.services.tiktok_client import TikTokShopIdentity, TikTokTokenSet
from erp_api.services.tiktok_reauthorization_repository import (
    TikTokConnectionTargetChanged,
    TikTokReauthorizationRepository,
)
from erp_api.services.token_cipher import TokenCipher

TENANT_ID = UUID("8b74818a-53e4-5a38-b52f-8b83fa06e3cf")
SHOP_ID = UUID("b252abf4-86c8-539b-956f-1fd1b0892dfe")


class FakeResult:
    def __init__(self, row: tuple[Shop, ShopConnection] | None) -> None:
        self._row = row

    def one_or_none(self) -> tuple[Shop, ShopConnection] | None:
        return self._row


class FakeSession:
    def __init__(self, row: tuple[Shop, ShopConnection] | None) -> None:
        self.row = row
        self.commits = 0
        self.rollbacks = 0

    async def execute(self, statement: object) -> FakeResult:
        assert getattr(statement, "_for_update_arg", None) is not None
        return FakeResult(self.row)

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


class FakeDatabase:
    def __init__(self, session: FakeSession) -> None:
        self._session = session

    async def session(self, tenant_id: UUID):
        assert tenant_id == TENANT_ID
        try:
            yield self._session
        except Exception:
            await self._session.rollback()
            raise


def _row(platform_shop_id: str = "shop-001") -> tuple[Shop, ShopConnection]:
    shop = Shop(
        id=SHOP_ID,
        tenant_id=TENANT_ID,
        platform="tiktok",
        platform_shop_id=platform_shop_id,
        shop_name="Old Name",
        region="US",
        status="active",
    )
    connection = ShopConnection(
        tenant_id=TENANT_ID,
        shop_id=SHOP_ID,
        auth_status="authorized",
        app_profile="legacy",
        access_token_ciphertext="old-access",
        refresh_token_ciphertext="old-refresh",
        shop_ciphertext="old-cipher",
        scopes=["seller.shop.info"],
        last_error="old error",
    )
    return shop, connection


def test_replace_connection_locks_target_and_commits_all_new_credentials() -> None:
    row = _row()
    session = FakeSession(row)
    cipher = TokenCipher("test-only-token-encryption-key-32-chars")
    repository = TikTokReauthorizationRepository(FakeDatabase(session), cipher)

    result = asyncio.run(
        repository.replace_connection(
            TENANT_ID,
            SHOP_ID,
            "shop-001",
            TikTokShopIdentity("shop-001", "New Name", "GB", "new-shop-cipher"),
            TikTokTokenSet(
                "new-access", "new-refresh", 3600, ["data.bestselling.public.read"]
            ),
            app_profile="301",
        )
    )

    shop, connection = row
    assert result.id == SHOP_ID
    assert session.commits == 1
    assert shop.shop_name == "New Name"
    assert shop.region == "GB"
    assert cipher.decrypt(connection.access_token_ciphertext) == "new-access"
    assert cipher.decrypt(connection.refresh_token_ciphertext) == "new-refresh"
    assert cipher.decrypt(connection.shop_ciphertext) == "new-shop-cipher"
    assert connection.scopes == ["data.bestselling.public.read"]
    assert connection.auth_status == "authorized"
    assert connection.app_profile == "301"
    assert connection.last_error is None


@pytest.mark.parametrize("platform_shop_id", ["shop-002", ""])
def test_replace_connection_rejects_changed_target_without_mutating_old_tokens(
    platform_shop_id: str,
) -> None:
    row = _row(platform_shop_id or "shop-001") if platform_shop_id else None
    session = FakeSession(row)
    repository = TikTokReauthorizationRepository(
        FakeDatabase(session), TokenCipher("test-only-token-encryption-key-32-chars")
    )

    with pytest.raises(TikTokConnectionTargetChanged):
        asyncio.run(
            repository.replace_connection(
                TENANT_ID,
                SHOP_ID,
                "shop-001",
                TikTokShopIdentity("shop-001", "New Name", "GB", "new-cipher"),
                TikTokTokenSet("new-access", "new-refresh", 3600, ["new.scope"]),
                app_profile="legacy",
            )
        )

    assert session.commits == 0
    if row:
        _, connection = row
        assert connection.access_token_ciphertext == "old-access"
        assert connection.scopes == ["seller.shop.info"]
