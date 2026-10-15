from __future__ import annotations

from datetime import datetime
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
)
from sqlalchemy import Uuid as SQLAlchemyUUID
from sqlalchemy.orm import Mapped, mapped_column

from erp_api.db.base import Base
from erp_api.db.tenant_scope import TenantScoped

SYNC_STATUSES = (
    "queued",
    "running",
    "retry_wait",
    "succeeded",
    "failed",
    "dead_letter",
    "cancelled",
)


class FinanceSyncRun(TenantScoped, Base):
    __tablename__ = "finance_sync_runs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["shop_id", "tenant_id"],
            ["shops.id", "shops.tenant_id"],
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "status IN ('queued', 'running', 'retry_wait', 'succeeded', "
            "'failed', 'dead_letter', 'cancelled')",
            name="ck_finance_sync_runs_status",
        ),
        CheckConstraint("window_to > window_from", name="ck_finance_sync_runs_window"),
        CheckConstraint(
            "fetched_count >= 0 AND written_count >= 0 AND skipped_count >= 0 "
            "AND failed_count >= 0 AND discrepancy_count >= 0",
            name="ck_finance_sync_runs_counts",
        ),
        Index(
            "ix_finance_sync_runs_window",
            "tenant_id",
            "shop_id",
            "entity_type",
            "window_from",
            "window_to",
            "status",
        ),
        Index(
            "ix_finance_sync_runs_status_started",
            "tenant_id",
            "status",
            "started_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    shop_id: Mapped[UUID] = mapped_column(SQLAlchemyUUID(as_uuid=True), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    mode: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    window_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    window_to: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recovery_cursor: Mapped[str | None] = mapped_column(Text)
    fetched_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    written_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    discrepancy_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_summary: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class FinanceSyncCursor(TenantScoped, Base):
    __tablename__ = "finance_sync_cursors"
    __table_args__ = (
        ForeignKeyConstraint(
            ["shop_id", "tenant_id"],
            ["shops.id", "shops.tenant_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "tenant_id",
            "shop_id",
            "entity_type",
            name="uq_finance_sync_cursors_tenant_shop_entity",
        ),
        Index(
            "ix_finance_sync_cursors_freshness",
            "tenant_id",
            "shop_id",
            "last_successful_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    shop_id: Mapped[UUID] = mapped_column(SQLAlchemyUUID(as_uuid=True), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    recovery_cursor: Mapped[str | None] = mapped_column(Text)
    committed_cursor: Mapped[str | None] = mapped_column(Text)
    last_successful_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
