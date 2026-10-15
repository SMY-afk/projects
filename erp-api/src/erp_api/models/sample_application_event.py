from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    DateTime,
    ForeignKeyConstraint,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy import Uuid as SQLAlchemyUUID
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from erp_api.db.base import Base
from erp_api.db.tenant_scope import TenantScoped


class SampleApplicationEvent(TenantScoped, Base):
    __tablename__ = "sample_application_events"
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
            "tenant_id",
            "shop_id",
            "event_source",
            "external_event_id",
            name="uq_sample_application_events_tenant_shop_source_external",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    shop_id: Mapped[UUID] = mapped_column(SQLAlchemyUUID(as_uuid=True), nullable=False)
    sample_application_id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    event_source: Mapped[str] = mapped_column(String(64), nullable=False)
    external_event_id: Mapped[str | None] = mapped_column(String(255))
    actor_id: Mapped[str | None] = mapped_column(String(255))
    actor_name: Mapped[str | None] = mapped_column(String(255))
    before_data: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    after_data: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
