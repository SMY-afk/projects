from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
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

if TYPE_CHECKING:
    from erp_api.models.order import Order


class OrderAttribution(TenantScoped, Base):
    """The current, tenant-scoped conversion-chain decision for an order."""

    __tablename__ = "order_attributions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["order_id", "tenant_id"],
            ["orders.id", "orders.tenant_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "tenant_id",
            "order_id",
            name="uq_order_attributions_tenant_order",
        ),
        Index(
            "ix_order_attributions_tenant_chain_code",
            "tenant_id",
            "chain_code",
        ),
        Index(
            "ix_order_attributions_tenant_classification_status",
            "tenant_id",
            "classification_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    order_id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), nullable=False, index=True
    )
    winning_evidence_link_id: Mapped[UUID | None] = mapped_column(
        SQLAlchemyUUID(as_uuid=True),
        ForeignKey("order_conversion_links.id", ondelete="SET NULL"),
        index=True,
    )
    traffic_source: Mapped[str] = mapped_column(String(32), nullable=False)
    operator_subject: Mapped[str] = mapped_column(String(32), nullable=False)
    entry_point: Mapped[str] = mapped_column(String(48), nullable=False)
    special_order_type: Mapped[str] = mapped_column(String(48), nullable=False)
    chain_code: Mapped[str] = mapped_column(String(160), nullable=False)
    classification_status: Mapped[str] = mapped_column(String(24), nullable=False)
    classification_method: Mapped[str] = mapped_column(String(32), nullable=False)
    platform_source_code: Mapped[str | None] = mapped_column(String(128))
    creator_external_id: Mapped[str | None] = mapped_column(String(128))
    video_external_id: Mapped[str | None] = mapped_column(String(128))
    live_external_id: Mapped[str | None] = mapped_column(String(128))
    product_external_id: Mapped[str | None] = mapped_column(String(128))
    sku_external_id: Mapped[str | None] = mapped_column(String(128))
    campaign_external_id: Mapped[str | None] = mapped_column(String(128))
    promotion_external_id: Mapped[str | None] = mapped_column(String(128))
    confidence_score: Mapped[float] = mapped_column(
        Numeric(5, 4), nullable=False, default=0
    )
    is_multi_touch: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    conflict_flags: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    evidence_summary: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    resolution_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    evidence_json: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    classified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    order: Mapped[Order] = relationship(back_populates="attribution")
