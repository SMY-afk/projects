from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
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


class SampleApplicationWorkflow(TenantScoped, Base):
    __tablename__ = "sample_application_workflows"
    __table_args__ = (
        ForeignKeyConstraint(
            ["shop_id", "tenant_id"],
            ["shops.id", "shops.tenant_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["sample_application_id", "tenant_id"],
            ["sample_applications.id", "sample_applications.tenant_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "sample_application_id",
            name="uq_sample_application_workflows_application",
        ),
        UniqueConstraint(
            "feishu_record_id", name="uq_sample_application_workflows_feishu_record"
        ),
        CheckConstraint(
            "assignment_version >= 0",
            name="ck_sample_application_workflows_assignment_version",
        ),
        CheckConstraint(
            "sync_status IN ('pending', 'succeeded', 'failed')",
            name="ck_sample_application_workflows_sync_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    shop_id: Mapped[UUID] = mapped_column(SQLAlchemyUUID(as_uuid=True), nullable=False)
    sample_application_id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), nullable=False
    )
    feishu_record_id: Mapped[str | None] = mapped_column(String(128))
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sync_hash: Mapped[str | None] = mapped_column(String(64))
    sync_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending"
    )
    assigned_bd_name: Mapped[str | None] = mapped_column(String(255))
    processing_status: Mapped[str | None] = mapped_column(String(64))
    processing_result: Mapped[str | None] = mapped_column(Text)
    business_note: Mapped[str | None] = mapped_column(Text)
    assignment_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    feishu_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
