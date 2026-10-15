from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import HTTPException, Request, status
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from erp_api.db.tenant_scope import (
    TenantContextError,
    register_tenant_scope_events,
    require_tenant_id,
)


class TenantSession(AsyncSession):
    """Async session whose ORM statements are always scoped to one tenant."""


register_tenant_scope_events(TenantSession.sync_session_class)


class Database:
    """Owns the application's async engine and request-scoped sessions."""

    def __init__(self, database_url: str) -> None:
        self.engine: AsyncEngine = create_async_engine(
            database_url,
            pool_pre_ping=True,
            hide_parameters=True,
        )
        self.session_factory = async_sessionmaker(
            self.engine,
            class_=TenantSession,
            expire_on_commit=False,
        )
        self.system_session_factory = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
            info={"system_scope": True},
        )

    async def dispose(self) -> None:
        await self.engine.dispose()

    async def session(self, tenant_id: UUID) -> AsyncIterator[TenantSession]:
        tenant_id = require_tenant_id(tenant_id)
        async with self.session_factory(
            info={"tenant_id": tenant_id}
        ) as database_session:
            try:
                yield database_session
            except Exception:
                await database_session.rollback()
                raise


async def get_db_session(request: Request) -> AsyncIterator[AsyncSession]:
    database: Database = request.app.state.database
    tenant_id = getattr(request.state, "tenant_id", None)
    try:
        tenant_id = require_tenant_id(tenant_id)
    except TenantContextError as error:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A verified tenant context is required.",
        ) from error
    async for database_session in database.session(tenant_id):
        yield database_session
