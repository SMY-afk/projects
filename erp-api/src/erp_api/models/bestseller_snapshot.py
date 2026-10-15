from __future__ import annotations

from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    Date,
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


class BestsellerSnapshot(TenantScoped, Base):
    __tablename__ = "bestseller_snapshots"
    __table_args__ = (
        ForeignKeyConstraint(
            ["shop_id", "tenant_id"],
            ["shops.id", "shops.tenant_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("id", "tenant_id", name="uq_bestseller_snapshots_id_tenant"),
        UniqueConstraint(
            "tenant_id",
            "shop_id",
            "entity_type",
            "reference_date",
            "time_slot",
            "currency",
            "author_type",
            name="uq_bestseller_snapshots_query",
        ),
        Index(
            "ix_bestseller_snapshots_shop_entity_date",
            "tenant_id",
            "shop_id",
            "entity_type",
            "reference_date",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    shop_id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), nullable=False, index=True
    )
    entity_type: Mapped[str] = mapped_column(String(16), nullable=False)
    reference_date: Mapped[date] = mapped_column(Date, nullable=False)
    time_slot: Mapped[str] = mapped_column(String(4), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    author_type: Mapped[str] = mapped_column(String(16), nullable=False)
    platform_request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    entry_count: Mapped[int] = mapped_column(Integer, nullable=False)
    is_stale: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    last_error_category: Mapped[str | None] = mapped_column(String(32))
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    refreshed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class BestsellerEntry(TenantScoped, Base):
    __tablename__ = "bestseller_entries"
    __table_args__ = (
        ForeignKeyConstraint(
            ["snapshot_id", "tenant_id"],
            ["bestseller_snapshots.id", "bestseller_snapshots.tenant_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "snapshot_id",
            "external_id",
            name="uq_bestseller_entries_snapshot_external",
        ),
        UniqueConstraint(
            "snapshot_id", "rank", name="uq_bestseller_entries_snapshot_rank"
        ),
        Index(
            "ix_bestseller_entries_tenant_snapshot_rank",
            "tenant_id",
            "snapshot_id",
            "rank",
        ),
        Index(
            "ix_bestseller_entries_raw_payload_expires_at",
            "raw_payload_expires_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    snapshot_id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), nullable=False
    )
    external_id: Mapped[str] = mapped_column(String(128), nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    display_name: Mapped[str | None] = mapped_column(Text)
    gmv_range_raw: Mapped[str] = mapped_column(Text, nullable=False)
    gmv_currency_context: Mapped[str] = mapped_column(String(8), nullable=False)
    extensions: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    raw_payload: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    raw_payload_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
