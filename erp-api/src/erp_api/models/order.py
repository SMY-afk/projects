from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    and_,
    func,
)
from sqlalchemy import Uuid as SQLAlchemyUUID
from sqlalchemy.orm import Mapped, foreign, mapped_column, relationship

from erp_api.db.base import Base
from erp_api.db.tenant_scope import TenantScoped
from erp_api.models.affiliate_order_item import AffiliateOrderItem

if TYPE_CHECKING:
    from erp_api.models.order_attribution import OrderAttribution
    from erp_api.models.order_conversion_link import OrderConversionLink
    from erp_api.models.order_fulfillment import OrderFulfillment
    from erp_api.models.order_line import OrderLine
    from erp_api.models.order_recipient import OrderRecipient
    from erp_api.models.shop import Shop


class Order(TenantScoped, Base):
    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("id", "tenant_id", name="uq_orders_id_tenant"),
        UniqueConstraint(
            "shop_id", "platform_order_id", name="uq_orders_shop_platform_order"
        ),
        ForeignKeyConstraint(
            ["shop_id", "tenant_id"],
            ["shops.id", "shops.tenant_id"],
            ondelete="CASCADE",
        ),
        Index(
            "ix_orders_tenant_shop_platform",
            "tenant_id",
            "shop_id",
            "platform_order_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    shop_id: Mapped[UUID] = mapped_column(
        SQLAlchemyUUID(as_uuid=True), nullable=False, index=True
    )
    platform_order_id: Mapped[str] = mapped_column(String(128), nullable=False)
    order_number: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="unknown", index=True
    )
    external_status: Mapped[str] = mapped_column(String(64), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    subtotal_amount_minor: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )
    shipping_fee_minor: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )
    discount_amount_minor: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )
    tax_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    total_amount_minor: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )
    buyer_username_masked: Mapped[str | None] = mapped_column(String(128))
    placed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    platform_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    shop: Mapped[Shop] = relationship(back_populates="orders")
    lines: Mapped[list[OrderLine]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )
    fulfillments: Mapped[list[OrderFulfillment]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )
    recipient: Mapped[OrderRecipient | None] = relationship(
        back_populates="order", cascade="all, delete-orphan", uselist=False
    )
    attribution: Mapped[OrderAttribution | None] = relationship(
        back_populates="order",
        cascade="all, delete-orphan",
        uselist=False,
    )
    conversion_links: Mapped[list[OrderConversionLink]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )
    affiliate_order_items: Mapped[list[AffiliateOrderItem]] = relationship(
        primaryjoin=lambda: and_(
            Order.tenant_id == foreign(AffiliateOrderItem.tenant_id),
            Order.shop_id == foreign(AffiliateOrderItem.shop_id),
            Order.platform_order_id == foreign(AffiliateOrderItem.main_order_id),
        ),
        order_by=lambda: (AffiliateOrderItem.order_created_at, AffiliateOrderItem.id),
        viewonly=True,
    )
