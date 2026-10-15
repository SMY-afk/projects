from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
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
    from erp_api.models.shop import Shop


class AffiliateOrderItem(TenantScoped, Base):
    """One source affiliate-order SKU row captured for a shop."""

    __tablename__ = "affiliate_order_items"
    __table_args__ = (
        ForeignKeyConstraint(
            ["shop_id", "tenant_id"],
            ["shops.id", "shops.tenant_id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "shop_id",
            "source_record_key",
            name="uq_affiliate_order_items_shop_source_record",
        ),
        Index(
            "ix_affiliate_order_items_shop_main_order",
            "shop_id",
            "main_order_id",
        ),
        Index(
            "ix_affiliate_order_items_shop_order_created_at",
            "shop_id",
            "order_created_at",
        ),
        Index(
            "ix_affiliate_order_items_shop_creator",
            "shop_id",
            "creator_id",
        ),
        Index(
            "ix_affiliate_order_items_shop_campaign",
            "shop_id",
            "campaign_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    shop_id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), nullable=False, index=True
    )
    main_order_id: Mapped[str] = mapped_column(String(128), nullable=False)
    creator_id: Mapped[str | None] = mapped_column(String(128))
    creator_nickname: Mapped[str | None] = mapped_column(String(255))
    campaign_id: Mapped[str | None] = mapped_column(String(128))
    product_id: Mapped[str] = mapped_column(String(128), nullable=False)
    product_name: Mapped[str | None] = mapped_column(String(500))
    image_uri: Mapped[str | None] = mapped_column(String(2000))
    sku_id: Mapped[str] = mapped_column(String(128), nullable=False)
    sku_name: Mapped[str | None] = mapped_column(String(500))
    order_created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    is_cod: Mapped[bool | None] = mapped_column(Boolean)
    is_non_same_shop_order: Mapped[bool | None] = mapped_column(Boolean)
    cos_type: Mapped[str | None] = mapped_column(String(64))
    promotion_id: Mapped[str | None] = mapped_column(String(128))
    promotion_type: Mapped[int | None] = mapped_column(Integer)
    content_form: Mapped[str | None] = mapped_column(String(32))
    commission_base: Mapped[Decimal | None] = mapped_column(Numeric(20, 4))
    commission_currency: Mapped[str | None] = mapped_column(String(10))
    commission_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    estimated_standard_commission: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 4)
    )
    raw_data: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    source_record_key: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    shop: Mapped[Shop] = relationship(back_populates="affiliate_order_items")
