from __future__ import annotations

from uuid import UUID

from sqlalchemy import ForeignKey, event
from sqlalchemy import Uuid as SQLAlchemyUUID
from sqlalchemy.orm import (
    Mapped,
    Session,
    declared_attr,
    mapped_column,
    with_loader_criteria,
)


class TenantContextError(RuntimeError):
    """Raised when a business operation has no trusted tenant context."""


class TenantScoped:
    """Marker and column definition for entities isolated by tenant."""

    @declared_attr
    def tenant_id(cls) -> Mapped[UUID]:
        return mapped_column(
            SQLAlchemyUUID(as_uuid=True),
            ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )


def require_tenant_id(tenant_id: UUID | None) -> UUID:
    if not isinstance(tenant_id, UUID):
        raise TenantContextError(
            "A trusted tenant context is required for business database access."
        )
    return tenant_id


def apply_tenant_criteria(statement, tenant_id: UUID):
    return statement.options(
        with_loader_criteria(
            TenantScoped,
            lambda model: model.tenant_id == tenant_id,
            include_aliases=True,
        )
    )


def scope_orm_statement(execute_state) -> None:
    if not (
        execute_state.is_select or execute_state.is_update or execute_state.is_delete
    ):
        return
    if execute_state.session.info.get("system_scope") is True:
        return
    tenant_id = require_tenant_id(execute_state.session.info.get("tenant_id"))
    execute_state.statement = apply_tenant_criteria(execute_state.statement, tenant_id)


def validate_tenant_writes(session, _flush_context, _instances) -> None:
    if session.info.get("system_scope") is True:
        return
    tenant_id = require_tenant_id(session.info.get("tenant_id"))
    for instance in session.new.union(session.dirty):
        if not isinstance(instance, TenantScoped):
            continue
        if instance in session.new and instance.tenant_id is None:
            instance.tenant_id = tenant_id
        elif instance.tenant_id != tenant_id:
            raise TenantContextError(
                "A business record cannot cross the active tenant boundary."
            )


def register_tenant_scope_events(session_class: type[Session]) -> None:
    event.listens_for(session_class, "do_orm_execute")(scope_orm_statement)
    event.listens_for(session_class, "before_flush")(validate_tenant_writes)
