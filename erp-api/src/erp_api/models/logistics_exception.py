from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, ClassVar
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy import Uuid as SQLAlchemyUUID
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from erp_api.db.base import Base
from erp_api.db.tenant_scope import TenantScoped

if TYPE_CHECKING:
    from erp_api.models.logistics_exception import LogisticsExceptionAction


EXCEPTION_TYPES = (
    "not_picked_up",
    "stalled",
    "address_error",
    "refused",
    "lost",
    "damaged",
    "platform_status_mismatch",
)
EXCEPTION_STATUSES = ("open", "claimed", "escalated", "resolved", "closed")
EXCEPTION_SEVERITIES = ("low", "medium", "high", "critical")


class LogisticsException(TenantScoped, Base):
    __tablename__ = "logistics_exceptions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["waybill_id", "tenant_id"],
            ["logistics_waybills.id", "logistics_waybills.tenant_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["package_id", "tenant_id"],
            ["logistics_packages.id", "logistics_packages.tenant_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["task_id", "tenant_id"],
            ["logistics_tasks.id", "logistics_tasks.tenant_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["source_event_id", "tenant_id"],
            ["logistics_tracking_events.id", "logistics_tracking_events.tenant_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("id", "tenant_id", name="uq_logistics_exceptions_id_tenant"),
        UniqueConstraint(
            "tenant_id",
            "exception_number",
            name="uq_logistics_exceptions_tenant_number",
        ),
        CheckConstraint(
            "exception_type IN ("
            + ", ".join(f"'{item}'" for item in EXCEPTION_TYPES)
            + ")",
            name="ck_logistics_exceptions_type",
        ),
        CheckConstraint(
            "status IN (" + ", ".join(f"'{item}'" for item in EXCEPTION_STATUSES) + ")",
            name="ck_logistics_exceptions_status",
        ),
        CheckConstraint(
            "severity IN ("
            + ", ".join(f"'{item}'" for item in EXCEPTION_SEVERITIES)
            + ")",
            name="ck_logistics_exceptions_severity",
        ),
        CheckConstraint(
            "source IN ('tracking_event', 'scheduled_scan')",
            name="ck_logistics_exceptions_source",
        ),
        Index(
            "uq_logistics_exceptions_active_fingerprint",
            "tenant_id",
            "fingerprint",
            unique=True,
            postgresql_where=text("status != 'closed'"),
        ),
        Index(
            "ix_logistics_exceptions_center",
            "tenant_id",
            "status",
            "severity",
            "last_detected_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    exception_number: Mapped[str] = mapped_column(String(40), nullable=False)
    waybill_id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), nullable=False
    )
    package_id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), nullable=False
    )
    task_id: Mapped[UUID] = mapped_column(SQLAlchemyUUID(as_uuid=True), nullable=False)
    source_event_id: Mapped[UUID | None] = mapped_column(SQLAlchemyUUID(as_uuid=True))
    exception_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    source: Mapped[str] = mapped_column(String(24), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(160), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    assigned_to_user_id: Mapped[UUID | None] = mapped_column(
        SQLAlchemyUUID(as_uuid=True)
    )
    resolution: Mapped[str | None] = mapped_column(Text)
    first_detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    last_detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    version_id: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )

    __mapper_args__: ClassVar[dict[str, object]] = {"version_id_col": version_id}

    actions: Mapped[list[LogisticsExceptionAction]] = relationship(
        back_populates="exception",
        cascade="all, delete-orphan",
        order_by="LogisticsExceptionAction.created_at",
    )


class LogisticsExceptionAction(TenantScoped, Base):
    __tablename__ = "logistics_exception_actions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["exception_id", "tenant_id"],
            ["logistics_exceptions.id", "logistics_exceptions.tenant_id"],
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "action_type IN ('detected', 'claimed', 'note_added', 'escalated', 'resolved', 'closed')",
            name="ck_logistics_exception_actions_type",
        ),
        Index(
            "ix_logistics_exception_actions_timeline",
            "tenant_id",
            "exception_id",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    exception_id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), nullable=False
    )
    action_type: Mapped[str] = mapped_column(String(24), nullable=False)
    actor_user_id: Mapped[UUID | None] = mapped_column(SQLAlchemyUUID(as_uuid=True))
    from_status: Mapped[str | None] = mapped_column(String(20))
    to_status: Mapped[str | None] = mapped_column(String(20))
    note: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict[str, object]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    exception: Mapped[LogisticsException] = relationship(back_populates="actions")
