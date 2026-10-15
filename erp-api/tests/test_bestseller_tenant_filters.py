from __future__ import annotations

import asyncio
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from erp_api.services.shop_repository import ShopRepository
from erp_api.services.token_cipher import TokenCipher


class EmptyResult:
    def one_or_none(self):
        return None


class FakeSession:
    def __init__(self) -> None:
        self.statement = None

    async def execute(self, statement):
        self.statement = statement
        return EmptyResult()


class FakeDatabase:
    def __init__(self, session) -> None:
        self.session_value = session

    async def session(self, tenant_id):
        yield self.session_value


def test_authorization_read_explicitly_filters_tenant_and_shop() -> None:
    tenant_id, shop_id = uuid4(), uuid4()
    session = FakeSession()
    repository = ShopRepository(
        FakeDatabase(session),
        TokenCipher("test-only-encryption-key-32-bytes-minimum"),
    )

    result = asyncio.run(repository.get_connection_status(tenant_id, shop_id))

    assert result is None
    compiled = session.statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "shops.tenant_id" in sql
    assert "shop_connections.tenant_id" in sql
    assert "shops.id" in sql
    assert tenant_id in compiled.params.values()
    assert shop_id in compiled.params.values()
