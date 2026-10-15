import asyncio
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

import erp_api.models  # noqa: F401 -- register all SQLAlchemy relationship targets
from erp_api.db.tenant_scope import (
    TenantContextError,
    TenantScoped,
    apply_tenant_criteria,
    scope_orm_statement,
)
from erp_api.infrastructure.database import Database
from erp_api.models.shop_connection import ShopConnection
from erp_api.models.user import User


def test_business_models_are_tenant_scoped() -> None:
    assert issubclass(User, TenantScoped)
    assert issubclass(ShopConnection, TenantScoped)


def test_tenant_criteria_filters_direct_entity_queries() -> None:
    tenant_id = UUID("4098933c-e0b4-5e44-8f57-e15a53aabc8b")
    statement = apply_tenant_criteria(select(User), tenant_id)
    sql = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "users.tenant_id" in sql
    assert str(tenant_id) in sql


def test_tenant_criteria_filters_shop_connection_queries() -> None:
    tenant_id = UUID("22e7e39a-7f46-5766-b85b-000bf93ad94f")
    statement = apply_tenant_criteria(select(ShopConnection), tenant_id)
    sql = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "shop_connections.tenant_id" in sql
    assert str(tenant_id) in sql


def test_orm_execution_scope_rejects_missing_tenant_context() -> None:
    execute_state = SimpleNamespace(
        is_select=True,
        is_update=False,
        is_delete=False,
        session=SimpleNamespace(info={}),
        statement=select(User),
    )

    with pytest.raises(TenantContextError):
        scope_orm_statement(execute_state)


def test_internal_system_scope_can_discover_tenants_without_weakening_request_scope() -> (
    None
):
    execute_state = SimpleNamespace(
        is_select=True,
        is_update=False,
        is_delete=False,
        session=SimpleNamespace(info={"system_scope": True}),
        statement=select(User),
    )

    scope_orm_statement(execute_state)

    assert execute_state.statement is not None


def test_database_session_rejects_missing_tenant_context() -> None:
    database = Database("postgresql+asyncpg://erp:test-only@localhost:5432/erp_test")

    async def open_session_without_tenant() -> None:
        async for _session in database.session(None):  # type: ignore[arg-type]
            pass

    with pytest.raises(TenantContextError):
        asyncio.run(open_session_without_tenant())

    asyncio.run(database.dispose())
