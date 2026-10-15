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


class SampleNotificationOutbox(TenantScoped, Base):
    __tablename__ = "sample_notification_outbox"
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
            "id", "tenant_id", name="uq_sample_notification_outbox_id_tenant"
        ),
        UniqueConstraint(
            "tenant_id",
            "shop_id",
            "sample_application_id",
            "assignment_version",
            "recipient_open_id",
            name="uq_sample_notification_outbox_assignment_recipient",
        ),
        CheckConstraint(
            "status IN ('pending', 'processing', 'sent', 'retry_wait', "
            "'failed', 'cancelled')",
            name="ck_sample_notification_outbox_status",
        ),
        CheckConstraint(
            "assignment_version > 0",
            name="ck_sample_notification_outbox_assignment_version",
        ),
        CheckConstraint(
            "attempt_count >= 0",
            name="ck_sample_notification_outbox_attempt_count",
        ),
        Index(
            "ix_sample_notification_outbox_due",
            "tenant_id",
            "status",
            "next_attempt_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    shop_id: Mapped[UUID] = mapped_column(SQLAlchemyUUID(as_uuid=True), nullable=False)
    sample_application_id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), nullable=False
    )
    assignment_version: Mapped[int] = mapped_column(Integer, nullable=False)
    recipient_open_id: Mapped[str] = mapped_column(String(255), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    last_error_summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
