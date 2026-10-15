import asyncio
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from erp_api.infrastructure.database import Database, TenantSession


def test_database_creates_an_async_session_factory() -> None:
    database = Database("postgresql+asyncpg://erp:test-only@localhost:5432/erp_test")
    session = database.session_factory(info={"tenant_id": uuid4()})

    assert isinstance(session, AsyncSession)
    assert isinstance(session, TenantSession)

    asyncio.run(session.close())
    asyncio.run(database.dispose())
