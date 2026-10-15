from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy import Uuid as SQLAlchemyUUID
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from erp_api.db.base import Base
from erp_api.db.tenant_scope import TenantScoped


class OrderConversionLink(TenantScoped, Base):
    """Auditable exact link between an ERP order and an external conversion."""

    __tablename__ = "order_conversion_links"
    __table_args__ = (
        ForeignKeyConstraint(
            ["order_id", "tenant_id"],
            ["orders.id", "orders.tenant_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "tenant_id",
            "order_id",
            "source_system",
            "external_conversion_id",
            "evidence_hash",
            name="uq_order_conversion_links_order_source_conversion_evidence",
        ),
        Index(
            "ix_order_conversion_links_tenant_source_record",
            "tenant_id",
            "source_system",
            "source_record_key",
        ),
        Index(
            "ix_order_conversion_links_tenant_creator",
            "tenant_id",
            "creator_external_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    order_id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), nullable=False, index=True
    )
    order_line_id: Mapped[UUID | None] = mapped_column(
        SQLAlchemyUUID(as_uuid=True),
        ForeignKey("order_lines.id", ondelete="SET NULL"),
        index=True,
    )
    scraped_data_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("scraped_data.id", ondelete="SET NULL"),
        index=True,
    )
    source_system: Mapped[str] = mapped_column(String(48), nullable=False)
    source_record_key: Mapped[str] = mapped_column(String(256), nullable=False)
    external_conversion_id: Mapped[str] = mapped_column(String(160), nullable=False)
    match_key_type: Mapped[str | None] = mapped_column(String(32))
    match_key_value: Mapped[str | None] = mapped_column(String(160))
    creator_external_id: Mapped[str | None] = mapped_column(String(128))
    video_external_id: Mapped[str | None] = mapped_column(String(128))
    live_external_id: Mapped[str | None] = mapped_column(String(128))
    product_external_id: Mapped[str | None] = mapped_column(String(128))
    sku_external_id: Mapped[str | None] = mapped_column(String(128))
    campaign_external_id: Mapped[str | None] = mapped_column(String(128))
    promotion_external_id: Mapped[str | None] = mapped_column(String(128))
    traffic_source_candidate: Mapped[str | None] = mapped_column(String(32))
    operator_subject_candidate: Mapped[str | None] = mapped_column(String(32))
    entry_point_candidate: Mapped[str | None] = mapped_column(String(48))
    evidence_strength: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence_score: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False)
    evidence_json: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    order = relationship("Order", back_populates="conversion_links")
