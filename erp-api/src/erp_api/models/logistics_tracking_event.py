from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import Uuid as SQLAlchemyUUID
from sqlalchemy.orm import Mapped, mapped_column

from erp_api.db.base import Base
from erp_api.db.tenant_scope import TenantScoped


class LogisticsTrackingEvent(TenantScoped, Base):
    __tablename__ = "logistics_tracking_events"
    __table_args__ = (
        UniqueConstraint(
            "id", "tenant_id", name="uq_logistics_tracking_events_id_tenant"
        ),
        ForeignKeyConstraint(
            ["waybill_id", "tenant_id"],
            ["logistics_waybills.id", "logistics_waybills.tenant_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["carrier_id", "tenant_id"],
            ["logistics_carriers.id", "logistics_carriers.tenant_id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "tenant_id",
            "waybill_id",
            "dedupe_key",
            name="uq_logistics_tracking_events_dedupe",
        ),
        CheckConstraint(
            "source IN ('webhook', 'poll')",
            name="ck_logistics_tracking_events_source",
        ),
        CheckConstraint(
            "normalized_status IS NULL OR normalized_status IN "
            "('info_received', 'picked_up', 'in_transit', 'out_for_delivery', "
            "'delivered', 'exception', 'returned', 'cancelled')",
            name="ck_logistics_tracking_events_status",
        ),
        Index(
            "ix_logistics_tracking_events_timeline",
            "tenant_id",
            "waybill_id",
            "occurred_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    waybill_id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), nullable=False
    )
    carrier_id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), nullable=False
    )
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    external_event_id: Mapped[str | None] = mapped_column(String(160))
    dedupe_key: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_status: Mapped[str] = mapped_column(String(128), nullable=False)
    normalized_status: Mapped[str | None] = mapped_column(String(32))
    sequence_no: Mapped[int | None] = mapped_column(BigInteger)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    location: Mapped[str | None] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    accepted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ignored_reason: Mapped[str | None] = mapped_column(String(64))
