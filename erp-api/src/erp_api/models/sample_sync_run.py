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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from erp_api.db.base import Base
from erp_api.db.tenant_scope import TenantScoped


class SampleSyncRun(TenantScoped, Base):
    __tablename__ = "sample_sync_runs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["shop_id", "tenant_id"],
            ["shops.id", "shops.tenant_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("id", "tenant_id", name="uq_sample_sync_runs_id_tenant"),
        CheckConstraint(
            "sync_type IN ('source_to_postgres', 'postgres_to_feishu', "
            "'feishu_to_postgres', 'reconciliation')",
            name="ck_sample_sync_runs_sync_type",
        ),
        CheckConstraint(
            "source_type IN ('official_api', 'hubstudio_cdp', 'postgresql', 'feishu')",
            name="ck_sample_sync_runs_source_type",
        ),
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'partial', 'failed')",
            name="ck_sample_sync_runs_status",
        ),
        CheckConstraint(
            "pages_read >= 0 AND records_read >= 0 AND records_created >= 0 "
            "AND records_updated >= 0 AND feishu_created >= 0 "
            "AND feishu_updated >= 0",
            name="ck_sample_sync_runs_counts",
        ),
        Index(
            "ix_sample_sync_runs_shop_status_started",
            "tenant_id",
            "shop_id",
            "status",
            "started_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    shop_id: Mapped[UUID] = mapped_column(SQLAlchemyUUID(as_uuid=True), nullable=False)
    sync_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    sample_type: Mapped[str] = mapped_column(String(16), nullable=False, default="free", server_default="free")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued")
    pages_read: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_read: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    feishu_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    feishu_updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_summary: Mapped[str | None] = mapped_column(Text)
    platform_request_ids: Mapped[list[str] | None] = mapped_column(JSONB)
    source_batch_ids: Mapped[list[str] | None] = mapped_column(JSONB)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
